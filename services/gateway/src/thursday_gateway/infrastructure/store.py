"""The gateway's SQLite store: projects, chats, outgoing messages, and the log of the agents' events.

Ingest deduplicates by `event_id`; each accepted event gets a gateway position (`pos`) that clients
use as their WebSocket cursor. Each event is projected into the read model (`projection`) in the
same transaction as the insert, so a duplicate can never double-apply. What clients ask about the
read model is answered by `read_model`.
"""

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from thursday_contracts.events import EventEnvelope

from thursday_gateway.domain.model import CHAT_DELETED, Chat, Outgoing, OutgoingStatus, Project, RecordState
from thursday_gateway.infrastructure.projection import project_event

SCHEMA = """
create table if not exists schema_version (version integer not null);
create table if not exists projects (project_id text primary key, name text not null, folder text not null,
    created_at text not null, state text not null);
create table if not exists chats (chat_id text primary key, project_id text not null, title text not null,
    created_at text not null, state text not null, last_activity text not null,
    direct integer not null default 0);
create index if not exists chats_project on chats(project_id);
create table if not exists outgoing (id integer primary key autoincrement, chat_id text not null,
    client_message_id text not null, text text not null, status text not null, created_at text not null,
    attempts integer not null default 0, error text not null default '', direct integer not null default 0,
    unique (chat_id, client_message_id));
create table if not exists events (pos integer primary key autoincrement, event_id text not null unique,
    source text not null, seq integer not null, ts text not null, type text not null, project_id text,
    chat_id text, task_id text, payload text not null, received_at text not null);
create index if not exists events_chat on events(chat_id, pos);
create index if not exists events_task on events(task_id, pos);
create table if not exists sources (source text primary key, last_seq integer not null);
create table if not exists tasks (task_id text primary key, chat_id text, project_id text, state text not null,
    pause_state text not null, instruction text not null default '', summary text not null default '',
    created_at text not null, updated_at text not null);
create index if not exists tasks_chat on tasks(chat_id, created_at);
create table if not exists approvals (approval_id text primary key, task_id text not null, chat_id text not null,
    tool text not null, summary text not null, arguments text not null, expires_at text not null,
    status text not null, requested_at text not null, resolved_at text);
create table if not exists notifications (id integer primary key autoincrement, kind text not null,
    title text not null, body text not null, chat_id text, task_id text, created_at text not null,
    read integer not null default 0);
create table if not exists messages (id integer primary key autoincrement, chat_id text not null, role text not null,
    text text not null, client_message_id text, pos integer not null, created_at text not null,
    direct integer not null default 0);
create index if not exists messages_chat on messages(chat_id, id);
create table if not exists settings (key text primary key, value text not null);
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path: Path) -> None:
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("pragma journal_mode=wal")
        self._db.executescript(SCHEMA)
        if self._db.execute("select count(*) from schema_version").fetchone()[0] == 0:
            self._db.execute("insert into schema_version values (1)")
        for table in ("chats", "outgoing", "messages"):  # databases made before direct mode
            self._add_column(table, "direct", "integer not null default 0")

    def _add_column(self, table: str, column: str, definition: str) -> None:
        if column not in {r["name"] for r in self._db.execute(f"pragma table_info({table})")}:
            self._db.execute(f"alter table {table} add column {column} {definition}")

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._db.execute("begin immediate")
            try:
                yield self._db
            except BaseException:
                self._db.execute("rollback")
                raise
            self._db.execute("commit")

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, params).fetchall()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # --- settings (non-secret, JSON) ----------------------------------------------------
    def get_setting(self, key: str) -> Any:
        rows = self.query("select value from settings where key = ?", (key,))
        return json.loads(rows[0]["value"]) if rows else None

    def set_setting(self, key: str, value: Any) -> None:
        with self.tx() as db:
            db.execute("insert or replace into settings values (?, ?)", (key, json.dumps(value)))

    # --- projects and chats --------------------------------------------------------------
    def add_project(self, p: Project) -> None:
        with self.tx() as db:
            db.execute(
                "insert into projects values (?,?,?,?,?)",
                (p.project_id, p.name, p.folder, p.created_at.isoformat(), p.state.value),
            )

    def save_project(self, p: Project) -> None:
        with self.tx() as db:
            db.execute(
                "update projects set name = ?, folder = ?, state = ? where project_id = ?",
                (p.name, p.folder, p.state.value, p.project_id),
            )

    def project(self, project_id: str) -> Project | None:
        rows = self.query("select * from projects where project_id = ?", (project_id,))
        return self._project(rows[0]) if rows else None

    def projects(self) -> list[Project]:
        return [self._project(r) for r in self.query("select * from projects where state = 'active' order by name")]

    @staticmethod
    def _project(r: sqlite3.Row) -> Project:
        return Project(
            r["project_id"], r["name"], r["folder"], datetime.fromisoformat(r["created_at"]), RecordState(r["state"])
        )

    def add_chat(self, c: Chat) -> None:
        with self.tx() as db:
            db.execute(
                "insert into chats (chat_id, project_id, title, created_at, state, last_activity, direct) "
                "values (?,?,?,?,?,?,?)",
                (
                    c.chat_id,
                    c.project_id,
                    c.title,
                    c.created_at.isoformat(),
                    c.state.value,
                    c.created_at.isoformat(),
                    int(c.direct),
                ),
            )

    def save_chat(self, c: Chat) -> None:
        with self.tx() as db:
            db.execute(
                "update chats set title = ?, state = ?, direct = ? where chat_id = ?",
                (c.title, c.state.value, int(c.direct), c.chat_id),
            )

    def chat(self, chat_id: str) -> Chat | None:
        rows = self.query("select * from chats where chat_id = ?", (chat_id,))
        return self._chat(rows[0]) if rows else None

    def begin_chat_delete(self, chat_id: str) -> None:
        """Mark the chat as being deleted and fail the messages still waiting to be sent in it, in one step: from
        here on nothing new starts in this chat."""
        with self.tx() as db:
            db.execute("update chats set state = 'deleting' where chat_id = ?", (chat_id,))
            db.execute(
                "update outgoing set status = 'failed', error = ? where chat_id = ? and status = 'queued'",
                (CHAT_DELETED, chat_id),
            )

    def chats(self, project_id: str) -> list[dict[str, Any]]:
        """A project's active chats, the most recently used first."""
        rows = self.query(
            "select * from chats where project_id = ? and state = 'active' order by last_activity desc", (project_id,)
        )
        return [dict(r) for r in rows]

    def chat_titles(self) -> dict[str, str]:
        """Every chat's title by id, including chats being deleted."""
        return {r["chat_id"]: r["title"] for r in self.query("select chat_id, title from chats")}

    def project_has_chats(self, project_id: str) -> bool:
        return bool(self.query("select 1 from chats where project_id = ? limit 1", (project_id,)))

    def chats_in_state(self, state: RecordState) -> list[Chat]:
        return [self._chat(r) for r in self.query("select * from chats where state = ?", (state.value,))]

    def projects_in_state(self, state: RecordState) -> list[Project]:
        return [self._project(r) for r in self.query("select * from projects where state = ?", (state.value,))]

    @staticmethod
    def _chat(r: sqlite3.Row) -> Chat:
        return Chat(
            r["chat_id"],
            r["project_id"],
            r["title"],
            datetime.fromisoformat(r["created_at"]),
            RecordState(r["state"]),
            bool(r["direct"]),
        )

    def purge_chat(self, chat_id: str) -> None:
        with self.tx() as db:
            for table in ("outgoing", "events", "tasks", "approvals", "notifications", "messages"):
                db.execute(f"delete from {table} where chat_id = ?", (chat_id,))  # noqa: S608 - fixed table names
            db.execute("delete from chats where chat_id = ?", (chat_id,))

    def purge_project(self, project_id: str) -> None:
        with self.tx() as db:
            for table in ("events", "tasks"):
                db.execute(f"delete from {table} where project_id = ?", (project_id,))  # noqa: S608 - fixed table names
            db.execute("delete from projects where project_id = ?", (project_id,))

    def open_task_ids(self, chat_id: str) -> list[str]:
        rows = self.query(
            "select task_id from tasks where chat_id = ? and state in ('submitted','working','input_required')",
            (chat_id,),
        )
        return [r["task_id"] for r in rows]

    def purge_orphans(self) -> int:
        """Remove rows that belong to chats or projects that no longer exist (left by earlier versions)."""
        removed = 0
        with self.tx() as db:
            for table in ("outgoing", "events", "tasks", "approvals", "notifications", "messages"):
                removed += db.execute(
                    f"delete from {table} where chat_id is not null and chat_id not in (select chat_id from chats)"  # noqa: S608
                ).rowcount
            for table in ("events", "tasks"):
                removed += db.execute(
                    f"delete from {table} where project_id is not null "  # noqa: S608
                    "and project_id not in (select project_id from projects)"
                ).rowcount
        return removed

    @staticmethod
    def _belongs(db: sqlite3.Connection, event: EventEnvelope) -> bool:
        """False for an event about a chat or project that was deleted (or is being deleted): it must not come back."""
        if event.chat_id is not None:
            return bool(
                db.execute("select 1 from chats where chat_id = ? and state = 'active'", (event.chat_id,)).fetchone()
            )
        if event.project_id is not None:
            return bool(db.execute("select 1 from projects where project_id = ?", (event.project_id,)).fetchone())
        return True

    # --- outgoing messages ---------------------------------------------------------------
    def enqueue(self, chat_id: str, client_message_id: str, text: str, direct: bool = False) -> tuple[Outgoing, bool]:
        """Idempotent on (chat, client_message_id). Returns the record and whether there is work to do for it.

        Sending a failed message again queues it again: the agents recognise the message by the same id,
        so a part that already happened is not repeated.
        """
        with self.tx() as db:
            existing = db.execute(
                "select * from outgoing where chat_id = ? and client_message_id = ?", (chat_id, client_message_id)
            ).fetchone()
            if existing and existing["status"] == "failed":
                db.execute("update outgoing set status = 'queued', error = '' where id = ?", (existing["id"],))
                row = db.execute("select * from outgoing where id = ?", (existing["id"],)).fetchone()
                return self._outgoing(row), True
            if existing:
                return self._outgoing(existing), False
            cursor = db.execute(
                "insert into outgoing (chat_id, client_message_id, text, status, created_at, direct) "
                "values (?,?,?,?,?,?)",
                (chat_id, client_message_id, text, "queued", now_iso(), int(direct)),
            )
            db.execute("update chats set last_activity = ? where chat_id = ?", (now_iso(), chat_id))
            row = db.execute("select * from outgoing where id = ?", (cursor.lastrowid,)).fetchone()
            return self._outgoing(row), True

    def next_queued(self) -> Outgoing | None:
        rows = self.query("select * from outgoing where status = 'queued' order by id limit 1")
        return self._outgoing(rows[0]) if rows else None

    def set_outgoing(self, out_id: int, status: OutgoingStatus, error: str = "", attempt: bool = False) -> None:
        with self.tx() as db:
            db.execute(
                "update outgoing set status = ?, error = ?, attempts = attempts + ? where id = ?",
                (status.value, error[:300], int(attempt), out_id),
            )

    def queued_count(self) -> int:
        return int(self.query("select count(*) as n from outgoing where status = 'queued'")[0]["n"])

    def pending_outgoing(self, chat_id: str) -> list[Outgoing]:
        return [
            self._outgoing(r)
            for r in self.query(
                "select * from outgoing where chat_id = ? and status != 'delivered' order by id", (chat_id,)
            )
        ]

    @staticmethod
    def _outgoing(r: sqlite3.Row) -> Outgoing:
        return Outgoing(
            r["id"],
            r["chat_id"],
            r["client_message_id"],
            r["text"],
            OutgoingStatus(r["status"]),
            datetime.fromisoformat(r["created_at"]),
            r["attempts"],
            r["error"],
            bool(r["direct"]),
        )

    # --- ingest and projection -----------------------------------------------------------
    def ingest(self, events: list[EventEnvelope]) -> tuple[list[tuple[int, EventEnvelope]], int]:
        """Store new events and project them. Returns (accepted with positions, duplicate count)."""
        accepted: list[tuple[int, EventEnvelope]] = []
        duplicates = 0
        with self.tx() as db:
            for event in events:
                if db.execute("select 1 from events where event_id = ?", (event.event_id,)).fetchone():
                    duplicates += 1
                    continue
                if not self._belongs(db, event):
                    # Counted as handled so the sender moves on, but nothing is stored.
                    db.execute(
                        "insert into sources values (?, ?) on conflict(source) do update set "
                        "last_seq = max(last_seq, excluded.last_seq)",
                        (event.source.value, event.seq),
                    )
                    duplicates += 1
                    continue
                cursor = db.execute(
                    "insert into events (event_id, source, seq, ts, type, project_id, chat_id, task_id, payload, "
                    "received_at) values (?,?,?,?,?,?,?,?,?,?)",
                    (
                        event.event_id,
                        event.source.value,
                        event.seq,
                        event.ts.isoformat(),
                        event.type.value,
                        event.project_id,
                        event.chat_id,
                        event.task_id,
                        json.dumps(event.payload),
                        now_iso(),
                    ),
                )
                pos = int(cursor.lastrowid or 0)
                db.execute(
                    "insert into sources values (?, ?) on conflict(source) do update set "
                    "last_seq = max(last_seq, excluded.last_seq)",
                    (event.source.value, event.seq),
                )
                project_event(db, pos, event)
                accepted.append((pos, event))
        return accepted, duplicates

    def last_seq(self) -> dict[str, int]:
        return {r["source"]: r["last_seq"] for r in self.query("select * from sources")}

    def last_pos(self) -> int:
        return int(self.query("select coalesce(max(pos), 0) as pos from events")[0]["pos"])

    # --- retention -----------------------------------------------------------------------
    def prune_events(self, older_than: timedelta) -> int:
        cutoff = (datetime.now(UTC) - older_than).isoformat()
        with self.tx() as db:
            return db.execute("delete from events where received_at < ?", (cutoff,)).rowcount
