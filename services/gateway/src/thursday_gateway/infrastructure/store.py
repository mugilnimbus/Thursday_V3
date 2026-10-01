"""The gateway's SQLite store: projects, chats, outgoing messages, and the read model.

The read model is a projection of the agents' events and can be rebuilt from their replay
endpoints. Ingest deduplicates by `event_id`; each accepted event gets a gateway position
(`pos`) that clients use as their WebSocket cursor. Projection happens in the same
transaction as the insert, so a duplicate can never double-apply.
"""

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from thursday_contracts.events import EventEnvelope, EventType

from thursday_gateway.domain.model import Chat, Outgoing, OutgoingStatus, Project, RecordState

SCHEMA = """
create table if not exists schema_version (version integer not null);
create table if not exists projects (project_id text primary key, name text not null, folder text not null,
    created_at text not null, state text not null);
create table if not exists chats (chat_id text primary key, project_id text not null, title text not null,
    created_at text not null, state text not null, last_activity text not null);
create index if not exists chats_project on chats(project_id);
create table if not exists outgoing (id integer primary key autoincrement, chat_id text not null,
    client_message_id text not null, text text not null, status text not null, created_at text not null,
    attempts integer not null default 0, error text not null default '', unique (chat_id, client_message_id));
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
    text text not null, client_message_id text, pos integer not null, created_at text not null);
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
                "insert into chats values (?,?,?,?,?,?)",
                (c.chat_id, c.project_id, c.title, c.created_at.isoformat(), c.state.value, c.created_at.isoformat()),
            )

    def save_chat(self, c: Chat) -> None:
        with self.tx() as db:
            db.execute("update chats set title = ?, state = ? where chat_id = ?", (c.title, c.state.value, c.chat_id))

    def chat(self, chat_id: str) -> Chat | None:
        rows = self.query("select * from chats where chat_id = ?", (chat_id,))
        return self._chat(rows[0]) if rows else None

    def chats(self, project_id: str) -> list[sqlite3.Row]:
        return self.query(
            "select * from chats where project_id = ? and state = 'active' order by last_activity desc", (project_id,)
        )

    def chats_in_state(self, state: RecordState) -> list[Chat]:
        return [self._chat(r) for r in self.query("select * from chats where state = ?", (state.value,))]

    def projects_in_state(self, state: RecordState) -> list[Project]:
        return [self._project(r) for r in self.query("select * from projects where state = ?", (state.value,))]

    @staticmethod
    def _chat(r: sqlite3.Row) -> Chat:
        return Chat(
            r["chat_id"], r["project_id"], r["title"], datetime.fromisoformat(r["created_at"]), RecordState(r["state"])
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
    def enqueue(self, chat_id: str, client_message_id: str, text: str) -> tuple[Outgoing, bool]:
        """Idempotent on (chat, client_message_id). Returns the record and whether it is new."""
        with self.tx() as db:
            existing = db.execute(
                "select * from outgoing where chat_id = ? and client_message_id = ?", (chat_id, client_message_id)
            ).fetchone()
            if existing:
                return self._outgoing(existing), False
            cursor = db.execute(
                "insert into outgoing (chat_id, client_message_id, text, status, created_at) values (?,?,?,?,?)",
                (chat_id, client_message_id, text, "queued", now_iso()),
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
                self._project_event(db, pos, event)
                accepted.append((pos, event))
        return accepted, duplicates

    def last_seq(self) -> dict[str, int]:
        return {r["source"]: r["last_seq"] for r in self.query("select * from sources")}

    def last_pos(self) -> int:
        return int(self.query("select coalesce(max(pos), 0) as pos from events")[0]["pos"])

    @staticmethod
    def _project_event(db: sqlite3.Connection, pos: int, e: EventEnvelope) -> None:
        p, ts = e.payload, e.ts.isoformat()
        if e.chat_id:
            db.execute("update chats set last_activity = ? where chat_id = ?", (ts, e.chat_id))
        if e.type is EventType.DELEGATION and e.task_id:
            db.execute(
                "insert into tasks (task_id, chat_id, project_id, state, pause_state, instruction, created_at, "
                "updated_at) values (?,?,?,?,?,?,?,?) on conflict(task_id) do update set "
                "instruction = excluded.instruction",
                (e.task_id, e.chat_id, e.project_id, "submitted", "none", str(p.get("instruction", "")), ts, ts),
            )
        elif e.type is EventType.TASK_STATE and e.task_id:
            db.execute(
                "insert into tasks (task_id, chat_id, project_id, state, pause_state, summary, created_at, "
                "updated_at) values (?,?,?,?,?,?,?,?) on conflict(task_id) do update set state = excluded.state, "
                "pause_state = excluded.pause_state, summary = case when excluded.summary != '' "
                "then excluded.summary else tasks.summary end, updated_at = excluded.updated_at",
                (
                    e.task_id,
                    e.chat_id,
                    e.project_id,
                    str(p.get("state", "")),
                    str(p.get("pause_state", "none")),
                    str(p.get("summary", "")),
                    ts,
                    ts,
                ),
            )
        elif e.type is EventType.APPROVAL_REQUESTED:
            db.execute(
                "insert or ignore into approvals values (?,?,?,?,?,?,?,?,?,NULL)",
                (
                    p["approval_id"],
                    p["task_id"],
                    p["chat_id"],
                    p["tool"],
                    p["summary"],
                    json.dumps(p.get("arguments", {})),
                    p["expires_at"],
                    "pending",
                    ts,
                ),
            )
            db.execute(
                "insert into notifications (kind, title, body, chat_id, task_id, created_at) values (?,?,?,?,?,?)",
                ("approval", "Approval needed", str(p["summary"])[:500], e.chat_id, e.task_id, ts),
            )
        elif e.type is EventType.APPROVAL_RESOLVED and p.get("approval_id"):
            db.execute(
                "update approvals set status = ?, resolved_at = ? where approval_id = ?",
                (str(p.get("outcome")), ts, p["approval_id"]),
            )
        elif e.type is EventType.NOTIFICATION:
            db.execute(
                "insert into notifications (kind, title, body, chat_id, task_id, created_at) values (?,?,?,?,?,?)",
                (
                    str(p.get("kind", "info")),
                    str(p.get("title", ""))[:200],
                    str(p.get("body", ""))[:2000],
                    e.chat_id,
                    e.task_id,
                    ts,
                ),
            )
        elif e.type in (EventType.USER_MESSAGE, EventType.ASSISTANT_MESSAGE) and e.chat_id:
            role = "user" if e.type is EventType.USER_MESSAGE else "assistant"
            client_id = p.get("client_message_id")
            db.execute(
                "insert into messages (chat_id, role, text, client_message_id, pos, created_at) values (?,?,?,?,?,?)",
                (e.chat_id, role, str(p.get("text", "")), client_id, pos, ts),
            )
            if role == "user" and client_id:
                db.execute(
                    "update outgoing set status = 'delivered' where chat_id = ? and client_message_id = ?",
                    (e.chat_id, client_id),
                )

    # --- read model queries --------------------------------------------------------------
    def events_after(self, pos: int, limit: int, chat_id: str | None = None) -> list[sqlite3.Row]:
        if chat_id is None:
            return self.query("select * from events where pos > ? order by pos limit ?", (pos, limit))
        return self.query(
            "select * from events where chat_id = ? and pos > ? order by pos limit ?", (chat_id, pos, limit)
        )

    def llm_calls(self, since: timedelta, limit: int = 2000) -> list[dict[str, Any]]:
        """Successful model calls in the period, oldest first: when, which agent, speed, and context use."""
        cutoff = (datetime.now(UTC) - since).isoformat()
        rows = self.query(
            "select ts, payload from (select pos, ts, payload from events where type = 'llm_call' and ts >= ? "
            "order by pos desc limit ?) order by pos",
            (cutoff, limit),
        )
        calls = []
        for row in rows:
            p = json.loads(row["payload"])
            if p.get("status") != "ok":
                continue
            calls.append(
                {
                    "ts": row["ts"],
                    "agent": p.get("agent"),
                    "tokens_per_second": p.get("tokens_per_second"),
                    "ttft_seconds": p.get("ttft_seconds"),
                    "input_tokens": (p.get("usage") or {}).get("input_tokens"),
                    "output_tokens": (p.get("usage") or {}).get("output_tokens"),
                    "context_length": p.get("context_length"),
                }
            )
        return calls

    def task_events(self, task_id: str, limit: int = 2000) -> list[sqlite3.Row]:
        return self.query("select * from events where task_id = ? order by pos limit ?", (task_id, limit))

    def prune_events(self, older_than: timedelta) -> int:
        cutoff = (datetime.now(UTC) - older_than).isoformat()
        with self.tx() as db:
            return db.execute("delete from events where received_at < ?", (cutoff,)).rowcount
