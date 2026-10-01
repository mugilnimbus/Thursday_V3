"""The voice agent's SQLite store: per-chat transcripts, delegated tasks, processed turns, prompts."""

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
create table if not exists schema_version (version integer not null);
create table if not exists transcript (id integer primary key autoincrement, chat_id text not null,
    message text not null, created_at text not null);
create index if not exists transcript_chat on transcript(chat_id, id);
create table if not exists tasks (task_id text primary key, chat_id text not null, project_id text not null,
    instruction text not null, state text not null, summary text not null default '', push_token text not null,
    approval_id text, approval_summary text, created_at text not null, updated_at text not null);
create index if not exists tasks_chat on tasks(chat_id, created_at);
create table if not exists turns (chat_id text not null, client_message_id text not null, reply text not null,
    created_at text not null, primary key (chat_id, client_message_id));
create table if not exists prompts (version integer primary key autoincrement, text text not null,
    created_at text not null);
create table if not exists settings (key text primary key, value text not null);
"""
TERMINAL = ("completed", "failed", "canceled", "rejected")


def now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class DelegatedTask:
    task_id: str
    chat_id: str
    project_id: str
    instruction: str
    state: str
    summary: str
    push_token: str
    approval_id: str | None
    approval_summary: str | None

    @property
    def open(self) -> bool:
        return self.state not in TERMINAL


class Store:
    def __init__(self, path: Path) -> None:
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("pragma journal_mode=wal")
        self._db.executescript(SCHEMA)
        if self._db.execute("select count(*) from schema_version").fetchone()[0] == 0:
            self._db.execute("insert into schema_version values (1)")

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

    def append(self, chat_id: str, messages: list[dict[str, Any]]) -> None:
        with self._lock:
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
        self._x("insert or replace into turns values (?,?,?,?)", (chat_id, client_message_id, reply, now()))

    # delegated tasks
    def add_task(self, t: DelegatedTask) -> None:
        self._x(
            "insert into tasks values (?,?,?,?,?,?,?,?,?,?,?)",
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
        tasks = [
            self._task(r)
            for r in self._q("select * from tasks where chat_id = ? order by created_at desc limit 20", (chat_id,))
        ]
        return [t for t in tasks if t.open] if open_only else tasks

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
        )

    def delete_chat(self, chat_id: str) -> None:
        with self._lock:
            for table in ("transcript", "tasks", "turns"):
                self._db.execute(f"delete from {table} where chat_id = ?", (chat_id,))  # noqa: S608 - fixed tables

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
