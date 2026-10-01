"""SQLite call and permission log, one file per project, owned by this server.

Every call is recorded with its arguments (size-capped), the permission decision it
received, the outcome, and the duration. Nothing is ever read back by other services.
"""

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

ARGUMENT_CHAR_LIMIT = 4000
RETENTION_SECONDS = 30 * 24 * 3600

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


@dataclass(frozen=True, slots=True)
class CallRecord:
    call_id: int
    started: float


class AuditLog:
    def __init__(self, path: Path) -> None:
        self._db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self._db.execute("pragma journal_mode=wal")
        self._db.executescript(_SCHEMA)
        if self._db.execute("select count(*) from schema_version").fetchone()[0] == 0:
            self._db.execute("insert into schema_version values (1)")
        self._db.execute("delete from calls where started_at < ?", (time.time() - RETENTION_SECONDS,))

    def start(self, tool: str, arguments: dict[str, object], permission: str) -> CallRecord:
        text = json.dumps(arguments, ensure_ascii=False, default=str)
        if len(text) > ARGUMENT_CHAR_LIMIT:
            text = text[:ARGUMENT_CHAR_LIMIT] + "...[truncated]"
        now = time.time()
        cursor = self._db.execute(
            "insert into calls (started_at, tool, arguments, permission) values (?, ?, ?, ?)",
            (now, tool, text, permission),
        )
        return CallRecord(int(cursor.lastrowid or 0), now)

    def finish(self, record: CallRecord, outcome: str, detail: str = "") -> None:
        self._db.execute(
            "update calls set finished_at = ?, outcome = ?, detail = ? where id = ?",
            (time.time(), outcome, detail[:500], record.call_id),
        )

    def recent(self, limit: int = 50) -> list[tuple[object, ...]]:
        return self._db.execute(
            "select tool, permission, outcome from calls order by id desc limit ?", (limit,)
        ).fetchall()

    def close(self) -> None:
        self._db.close()
