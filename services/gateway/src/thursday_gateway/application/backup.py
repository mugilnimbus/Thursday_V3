"""Backup orchestration: ask every service to copy its own data into one timestamped folder.

The folder is sensitive (transcripts, projects, device token hashes). `.env` is never included.
A service that is down makes the run partial; the manifest records what was copied.
"""

import asyncio
import json
import logging
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from thursday_runtime.backup import backup_sqlite

from thursday_gateway.application.ports import BackupParticipants, SettingsRecords
from thursday_gateway.application.waiting import wait_any
from thursday_gateway.domain.model import InvalidInput

log = logging.getLogger(__name__)
PREFIX = "thursday-backup-"


class BackupSettings(BaseModel):
    folder: str = ""
    daily: bool = False
    keep_copies: int = Field(default=7, ge=1, le=365)


class BackupService:
    def __init__(
        self,
        store: SettingsRecords,
        own_files: list[Path],
        participants: BackupParticipants,
        defaults: BackupSettings,
    ) -> None:
        self._store = store
        self._own_files = own_files
        self._participants = participants
        self._defaults = defaults
        self._lock = asyncio.Lock()

    def settings(self) -> BackupSettings:
        saved = self._store.get_setting("backup")
        return BackupSettings.model_validate(saved) if saved is not None else self._defaults

    def save_settings(self, new: BackupSettings) -> BackupSettings:
        if new.folder and not Path(new.folder).is_absolute():
            raise InvalidInput("backup folder must be an absolute path")
        self._store.set_setting("backup", new.model_dump())
        return new

    def last_run(self) -> dict[str, Any] | None:
        return self._store.get_setting("backup_last")

    async def run(self) -> dict[str, Any]:
        settings = self.settings()
        if not settings.folder:
            raise InvalidInput("choose a backup folder first")
        async with self._lock:
            started = datetime.now(UTC)
            target = self._new_folder(Path(settings.folder), started)
            manifest: dict[str, Any] = {"created_at": started.isoformat(), "services": {}}
            gateway_dir = target / "gateway"
            manifest["services"]["gateway"] = {
                "ok": True,
                "files": {
                    f.name: await asyncio.to_thread(backup_sqlite, f, gateway_dir / f.name)
                    for f in self._own_files
                    if f.exists()
                },
            }
            for name in self._participants.names():
                manifest["services"][name] = await self._participants.copy(name, str(target))
            manifest["complete"] = all(s["ok"] for s in manifest["services"].values())
            (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            self._prune(Path(settings.folder), settings.keep_copies)
            summary = {
                "folder": str(target),
                "complete": manifest["complete"],
                "created_at": started.isoformat(),
                "services": {k: v["ok"] for k, v in manifest["services"].items()},
            }
            self._store.set_setting("backup_last", summary)
            return summary

    @staticmethod
    def _new_folder(folder: Path, started: datetime) -> Path:
        """A folder of its own for this run: two runs in the same second get different names, in order."""
        name = f"{PREFIX}{started.strftime('%Y%m%d-%H%M%S')}"
        folder.mkdir(parents=True, exist_ok=True)
        taken = sorted(p.name for p in folder.iterdir() if p.name.startswith(name))
        if not taken:
            target = folder / name
        else:  # after the newest of this second, also when earlier ones were removed since
            last = taken[-1].removeprefix(name).lstrip("-")
            target = folder / f"{name}-{(int(last) if last.isdigit() else 1) + 1:02d}"
        target.mkdir(exist_ok=False)
        return target

    @staticmethod
    def _complete(copy: Path) -> bool:
        try:
            return json.loads((copy / "manifest.json").read_text(encoding="utf-8")).get("complete") is True
        except (OSError, ValueError, AttributeError):
            return False

    @classmethod
    def _prune(cls, folder: Path, keep: int) -> None:
        """Keep the newest copies. The newest complete one is never removed, however many partial runs follow."""
        copies = sorted(p for p in folder.iterdir() if p.is_dir() and p.name.startswith(PREFIX))
        kept, old = copies[-keep:], copies[:-keep]
        if not any(cls._complete(c) for c in kept):
            last_complete = next((c for c in reversed(old) if cls._complete(c)), None)
            old = [c for c in old if c != last_complete]
        for copy in old:
            shutil.rmtree(copy, ignore_errors=True)

    async def run_daily(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            settings = self.settings()
            last = self.last_run()
            due = last is None or datetime.fromisoformat(last["created_at"]) <= datetime.now(UTC) - timedelta(days=1)
            if settings.daily and settings.folder and due:
                try:
                    await self.run()
                except Exception:
                    log.exception("daily backup failed")
            await wait_any(stop, timeout=3600)
