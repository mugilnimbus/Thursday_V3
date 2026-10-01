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

import httpx
from pydantic import BaseModel, Field, SecretStr
from thursday_runtime.backup import backup_sqlite

from thursday_gateway.application.waiting import wait_any
from thursday_gateway.domain.model import InvalidInput
from thursday_gateway.infrastructure.store import Store

log = logging.getLogger(__name__)
PREFIX = "thursday-backup-"


class BackupSettings(BaseModel):
    folder: str = ""
    daily: bool = False
    keep_copies: int = Field(default=7, ge=1, le=365)


class BackupService:
    def __init__(
        self,
        store: Store,
        own_files: list[Path],
        agents: dict[str, str],
        token: SecretStr,
        defaults: BackupSettings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._store = store
        self._own_files = own_files
        self._agents = agents
        self._headers = {"Authorization": f"Bearer {token.get_secret_value()}"}
        self._client = client or httpx.AsyncClient(timeout=120)
        self._defaults = defaults
        self._lock = asyncio.Lock()
        with store.tx() as db:
            db.execute("create table if not exists settings (key text primary key, value text not null)")

    def settings(self) -> BackupSettings:
        rows = self._store.query("select value from settings where key = 'backup'")
        return BackupSettings.model_validate_json(rows[0]["value"]) if rows else self._defaults

    def save_settings(self, new: BackupSettings) -> BackupSettings:
        if new.folder and not Path(new.folder).is_absolute():
            raise InvalidInput("backup folder must be an absolute path")
        with self._store.tx() as db:
            db.execute("insert or replace into settings values ('backup', ?)", (new.model_dump_json(),))
        return new

    def last_run(self) -> dict[str, Any] | None:
        rows = self._store.query("select value from settings where key = 'backup_last'")
        return json.loads(rows[0]["value"]) if rows else None

    async def run(self) -> dict[str, Any]:
        settings = self.settings()
        if not settings.folder:
            raise InvalidInput("choose a backup folder first")
        async with self._lock:
            started = datetime.now(UTC)
            target = Path(settings.folder) / f"{PREFIX}{started.strftime('%Y%m%d-%H%M%S')}"
            target.mkdir(parents=True, exist_ok=False)
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
            for name, base_url in self._agents.items():
                try:
                    response = await self._client.post(
                        f"{base_url}/v1/backup", json={"target_dir": str(target)}, headers=self._headers
                    )
                    response.raise_for_status()
                    manifest["services"][name] = {"ok": True, "files": response.json().get("files", {})}
                except httpx.HTTPError as exc:
                    manifest["services"][name] = {"ok": False, "error": type(exc).__name__}
            manifest["complete"] = all(s["ok"] for s in manifest["services"].values())
            (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            self._prune(Path(settings.folder), settings.keep_copies)
            summary = {
                "folder": str(target),
                "complete": manifest["complete"],
                "created_at": started.isoformat(),
                "services": {k: v["ok"] for k, v in manifest["services"].items()},
            }
            with self._store.tx() as db:
                db.execute("insert or replace into settings values ('backup_last', ?)", (json.dumps(summary),))
            return summary

    @staticmethod
    def _prune(folder: Path, keep: int) -> None:
        copies = sorted(p for p in folder.iterdir() if p.is_dir() and p.name.startswith(PREFIX))
        for old in copies[:-keep]:
            shutil.rmtree(old, ignore_errors=True)

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
