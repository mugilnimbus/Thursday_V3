"""SQLite call and permission log, one file per project, owned by this server.

Every call is recorded with its arguments (size-capped), the permission decision it
received, the outcome, the duration, and the chat it was made for. Nothing is ever read
back by other services. Old calls leave after the retention period; a deleted chat's
calls leave at once.
"""

import contextlib
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

ARGUMENT_CHAR_LIMIT = 4000
DEFAULT_KEEP_DAYS = 30
PRUNE_EVERY_SECONDS = 3600.0

_SCHEMA = """
create table if not exists schema_version (version integer not null);
create table if not exists calls (
    id integer primary key,
    started_at real not null,
    finished_at real,
    tool text not null,
    arguments text not null,
    permission text not null,
    outcome text,
    detail text
);
create index if not exists calls_started on calls(started_at);
"""
# Forward-only changes after the first schema, applied once each, in order.
_MIGRATIONS = {
    2: "alter table calls add column chat_id text; create index if not exists calls_chat on calls(chat_id);",
}


@dataclass(frozen=True, slots=True)
class CallRecord:
    call_id: int
    started: float


class AuditLog:
    def __init__(self, path: Path, keep_days: int = DEFAULT_KEEP_DAYS) -> None:
        """`keep_days` is how long calls are kept; 0 keeps them until their chat or project is deleted."""
        self._db = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=10)
        self._db.execute("pragma journal_mode=wal")
        self._db.executescript(_SCHEMA)
        version = self._db.execute("select max(version) from schema_version").fetchone()[0]
        if version is None:
            self._db.execute("insert into schema_version values (1)")
            version = 1
        for target in sorted(v for v in _MIGRATIONS if v > version):
            self._db.executescript(_MIGRATIONS[target])
            self._db.execute("insert into schema_version values (?)", (target,))
        self._keep_days = keep_days
        self._pruned_at = 0.0
        self.prune()

    def prune(self) -> int:
        """Remove calls older than the retention period. Returns how many went."""
        self._pruned_at = time.monotonic()
        if self._keep_days <= 0:
            return 0
        cutoff = time.time() - self._keep_days * 24 * 3600
        return self._db.execute("delete from calls where started_at < ?", (cutoff,)).rowcount

    def start(self, tool: str, arguments: dict[str, object], permission: str, chat_id: str | None = None) -> CallRecord:
        if time.monotonic() - self._pruned_at > PRUNE_EVERY_SECONDS:  # a server can stay up for days
            self.prune()
        text = json.dumps(arguments, ensure_ascii=False, default=str)
        if len(text) > ARGUMENT_CHAR_LIMIT:
            text = text[:ARGUMENT_CHAR_LIMIT] + "...[truncated]"
        now = time.time()
        cursor = self._db.execute(
            "insert into calls (started_at, tool, arguments, permission, chat_id) values (?, ?, ?, ?, ?)",
            (now, tool, text, permission, chat_id),
        )
        return CallRecord(int(cursor.lastrowid or 0), now)

    def finish(self, record: CallRecord, outcome: str, detail: str = "") -> None:
        self._db.execute(
            "update calls set finished_at = ?, outcome = ?, detail = ? where id = ?",
            (time.time(), outcome, detail[:500], record.call_id),
        )

    def forget_chat(self, chat_id: str) -> int:
        """Remove every call made for a chat. Returns how many there were."""
        return self._db.execute("delete from calls where chat_id = ?", (chat_id,)).rowcount

    def recent(self, limit: int = 50) -> list[tuple[object, ...]]:
        return self._db.execute(
            "select tool, permission, outcome, chat_id from calls order by id desc limit ?", (limit,)
        ).fetchall()

    def close(self) -> None:
        self._db.close()


def forget_chat(folder: Path, chat_id: str) -> int:
    """Remove a deleted chat's calls from every project's log in the folder. Safe to repeat."""
    removed = 0
    for path in sorted(folder.glob("*.sqlite")):
        log = AuditLog(path, keep_days=0)
        try:
            removed += log.forget_chat(chat_id)
        finally:
            log.close()
    return removed


def remove_project(folder: Path, project_id: str) -> list[str]:
    """Delete a deleted project's log and its side files. Returns the names that were there."""
    audit = folder / f"{project_id}.sqlite"
    removed = []
    for path in (audit, audit.with_name(audit.name + "-wal"), audit.with_name(audit.name + "-shm")):
        with contextlib.suppress(OSError):
            if path.exists():
                path.unlink()
                removed.append(path.name)
    return removed
