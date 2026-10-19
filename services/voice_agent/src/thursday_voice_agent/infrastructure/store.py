"""The voice agent's SQLite store: per-chat transcripts, delegated tasks, processed turns, prompts."""

import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from thursday_voice_agent.domain.tasks import DelegatedTask

SCHEMA = """
create table if not exists schema_version (version integer not null);
create table if not exists transcript (id integer primary key autoincrement, chat_id text not null,
    message text not null, created_at text not null);
create index if not exists transcript_chat on transcript(chat_id, id);
create table if not exists tasks (task_id text primary key, chat_id text not null, project_id text not null,
    instruction text not null, state text not null, summary text not null default '', push_token text not null,
    approval_id text, approval_summary text, created_at text not null, updated_at text not null,
    direct integer not null default 0);
create index if not exists tasks_chat on tasks(chat_id, created_at);
create table if not exists turns (chat_id text not null, client_message_id text not null, reply text not null,
    created_at text not null, primary key (chat_id, client_message_id));
create table if not exists prompts (version integer primary key autoincrement, text text not null,
    created_at text not null);
create table if not exists settings (key text primary key, value text not null);
create table if not exists deleted_chats (chat_id text primary key, deleted_at text not null);
"""
DELETED_NOTE_DAYS = 7
"""How long the note "this chat was deleted" is kept. Work that was under way when a chat was deleted ends within
hours; after a week nothing can still arrive for it."""


def now() -> str:
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
        self._add_column("tasks", "direct", "integer not null default 0")  # databases made before direct mode

    def _add_column(self, table: str, column: str, definition: str) -> None:
        if column not in {r["name"] for r in self._db.execute(f"pragma table_info({table})")}:
            self._db.execute(f"alter table {table} add column {column} {definition}")

    def _q(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, params).fetchall()

    def _x(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        with self._lock:
            return self._db.execute(sql, params).rowcount

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # transcript
    def transcript(self, chat_id: str, limit: int = 200) -> list[dict[str, Any]]:
        rows = self._q(
            "select message from (select id, message from transcript where chat_id = ? order by id desc "
            "limit ?) order by id",
            (chat_id, limit),
        )
        return [json.loads(r["message"]) for r in rows]

    def transcript_count(self, chat_id: str) -> int:
        return int(self._q("select count(*) from transcript where chat_id = ?", (chat_id,))[0][0])

    def transcript_from(self, chat_id: str, start: int) -> list[dict[str, Any]]:
        """The chat's messages from the one at position `start` (0 is the first) to the newest."""
        rows = self._q(
            "select message from transcript where chat_id = ? order by id limit -1 offset ?", (chat_id, start)
        )
        return [json.loads(r["message"]) for r in rows]

    def append(self, chat_id: str, messages: list[dict[str, Any]]) -> None:
        with self._lock:
            if self.chat_deleted(chat_id):
                return
            self._db.executemany(
                "insert into transcript (chat_id, message, created_at) values (?,?,?)",
                [(chat_id, json.dumps(m, default=str), now()) for m in messages],
            )

    # turns (idempotency)
    def turn_reply(self, chat_id: str, client_message_id: str) -> str | None:
        rows = self._q(
            "select reply from turns where chat_id = ? and client_message_id = ?", (chat_id, client_message_id)
        )
        return rows[0]["reply"] if rows else None

    def save_turn(self, chat_id: str, client_message_id: str, reply: str) -> None:
        with self._lock:
            if not self.chat_deleted(chat_id):
                self._x("insert or replace into turns values (?,?,?,?)", (chat_id, client_message_id, reply, now()))

    def prune_turns(self, before: datetime) -> int:
        """Forget which messages were answered before the moment given. Returns how many records went."""
        return self._x("delete from turns where created_at < ?", (before.isoformat(),))

    # delegated tasks
    def add_task(self, t: DelegatedTask) -> None:
        """Remember a task that was handed over. A task that is already known stays as it is: a request that was
        sent again is answered with the task its first sending started."""
        if self.chat_deleted(t.chat_id):
            return
        self._x(
            "insert or ignore into tasks (task_id, chat_id, project_id, instruction, state, summary, push_token, "
            "approval_id, approval_summary, created_at, updated_at, direct) values (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                t.task_id,
                t.chat_id,
                t.project_id,
                t.instruction,
                t.state,
                t.summary,
                t.push_token,
                t.approval_id,
                t.approval_summary,
                now(),
                now(),
                int(t.direct),
            ),
        )

    def task(self, task_id: str) -> DelegatedTask | None:
        rows = self._q("select * from tasks where task_id = ?", (task_id,))
        return self._task(rows[0]) if rows else None

    def update_task(
        self,
        task_id: str,
        state: str,
        summary: str | None = None,
        approval: tuple[str, str] | None = None,
        clear_approval: bool = False,
    ) -> None:
        sets, params = ["state = ?", "updated_at = ?"], [state, now()]
        if summary is not None:
            sets.append("summary = ?")
            params.append(summary)
        if approval is not None:
            sets += ["approval_id = ?", "approval_summary = ?"]
            params += list(approval)
        elif clear_approval:
            sets += ["approval_id = NULL", "approval_summary = NULL"]
        self._x(f"update tasks set {', '.join(sets)} where task_id = ?", (*params, task_id))  # noqa: S608 - fixed columns

    def tasks_for_chat(self, chat_id: str, open_only: bool = False) -> list[DelegatedTask]:
        """The chat's newest tasks. With `open_only`, every task that has not ended, however old it is."""
        if open_only:
            rows = self._q("select * from tasks where chat_id = ? order by created_at desc", (chat_id,))
            return [t for t in (self._task(r) for r in rows) if t.open]
        return [
            self._task(r)
            for r in self._q("select * from tasks where chat_id = ? order by created_at desc limit 20", (chat_id,))
        ]

    def open_tasks(self) -> list[DelegatedTask]:
        return [t for t in (self._task(r) for r in self._q("select * from tasks")) if t.open]

    def pending_approval(self, chat_id: str) -> DelegatedTask | None:
        rows = self._q(
            "select * from tasks where chat_id = ? and approval_id is not null and state = 'input_required' "
            "order by updated_at desc limit 1",
            (chat_id,),
        )
        return self._task(rows[0]) if rows else None

    @staticmethod
    def _task(r: sqlite3.Row) -> DelegatedTask:
        return DelegatedTask(
            r["task_id"],
            r["chat_id"],
            r["project_id"],
            r["instruction"],
            r["state"],
            r["summary"],
            r["push_token"],
            r["approval_id"],
            r["approval_summary"],
            bool(r["direct"]),
        )

    def delete_chat(self, chat_id: str) -> None:
        """Remove everything kept for the chat, and note that it was deleted: from here on nothing is written for
        it again, whatever was still under way (a reply being written, a task's report). Safe to repeat."""
        with self._lock:
            for table in ("transcript", "tasks", "turns"):
                self._db.execute(f"delete from {table} where chat_id = ?", (chat_id,))  # noqa: S608 - fixed tables
            self._db.execute("insert or replace into deleted_chats values (?, ?)", (chat_id, now()))
            old = (datetime.now(UTC) - timedelta(days=DELETED_NOTE_DAYS)).isoformat()
            self._db.execute("delete from deleted_chats where deleted_at < ?", (old,))

    def chat_deleted(self, chat_id: str) -> bool:
        return bool(self._q("select 1 from deleted_chats where chat_id = ?", (chat_id,)))

    # settings (non-secret, JSON)
    def get_setting(self, key: str) -> Any:
        rows = self._q("select value from settings where key = ?", (key,))
        return json.loads(rows[0]["value"]) if rows else None

    def set_setting(self, key: str, value: Any) -> None:
        self._x("insert or replace into settings values (?, ?)", (key, json.dumps(value)))

    # prompts
    def prompt_versions(self) -> list[tuple[int, str, str]]:
        return [
            (r[0], r[1], r[2]) for r in self._q("select version, created_at, text from prompts order by version desc")
        ]

    def current_prompt(self) -> tuple[int, str] | None:
        rows = self._q("select version, text from prompts order by version desc limit 1")
        return (rows[0][0], rows[0][1]) if rows else None

    def save_prompt(self, text: str) -> int:
        with self._lock:
            return int(
                self._db.execute("insert into prompts (text, created_at) values (?, ?)", (text, now())).lastrowid or 0
            )
