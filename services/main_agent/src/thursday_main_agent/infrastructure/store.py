"""The main agent's SQLite store: tasks, approvals, allow rules, call marks, chat transcripts,
and system prompt versions (events go through the shared outbox). No other service reads it.

One connection guarded by a lock: writes are small and local, and the lock makes
"first answer wins" a plain check-and-set.
"""

import json
import shutil
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from thursday_contracts.approvals import ApprovalDecision
from thursday_contracts.task_control import PauseState

from thursday_main_agent.domain.approvals import AllowRule, Approval, ApprovalStatus
from thursday_main_agent.domain.tasks import TaskPhase, TaskRecord
from thursday_main_agent.domain.tool_calls import CallMark, MarkState

MIGRATIONS: list[str] = [
    """
    create table tasks (
        task_id text primary key, chat_id text not null, project_id text not null, project_folder text not null,
        instruction text not null, created_at text not null, phase text not null, pause_state text not null,
        timeout_streak integer not null, history_len integer not null, transcript_saved integer not null
    );
    create index tasks_chat on tasks(chat_id);
    create table approvals (
        approval_id text primary key, task_id text not null, chat_id text not null, call_key text not null,
        tool text not null, summary text not null, arguments text not null, created_at text not null,
        expires_at text not null, status text not null, decision text, resolved_by text
    );
    create index approvals_call on approvals(call_key);
    create index approvals_status on approvals(status, expires_at);
    create table allow_rules (chat_id text not null, tool text not null, created_at text not null,
                              primary key (chat_id, tool));
    create table call_marks (key text primary key, task_id text not null, tool text not null, state text not null,
                             result text, is_error integer not null);
    create table transcript (id integer primary key, chat_id text not null, task_id text not null,
                             message text not null);
    create index transcript_chat on transcript(chat_id, id);
    create table prompts (version integer primary key autoincrement, text text not null, created_at text not null);
    """,
    """
    create table chat_summaries (chat_id text primary key, upto integer not null, summary text not null,
                                 updated_at text not null);
    """,
    """
    create table settings (key text primary key, value text not null);
    """,
]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


class Store:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("pragma journal_mode=wal")
        self._db.execute("pragma foreign_keys=on")
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            self._db.execute("create table if not exists schema_version (version integer not null)")
            row = self._db.execute("select max(version) from schema_version").fetchone()
            current = row[0] or 0
            if current < len(MIGRATIONS) and current > 0:
                shutil.copyfile(self._path, self._path.with_suffix(f".v{current}.bak"))
            for version in range(current + 1, len(MIGRATIONS) + 1):
                with self._tx() as db:
                    for statement in filter(str.strip, MIGRATIONS[version - 1].split(";")):
                        db.execute(statement)
                    db.execute("insert into schema_version values (?)", (version,))

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._db.execute("begin immediate")
            try:
                yield self._db
            except BaseException:
                self._db.execute("rollback")
                raise
            self._db.execute("commit")

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # --- tasks -------------------------------------------------------------------------
    def insert_task(self, task: TaskRecord) -> None:
        with self._tx() as db:
            db.execute("insert into tasks values (?,?,?,?,?,?,?,?,?,?,?)", self._task_row(task))

    def save_task(self, task: TaskRecord) -> None:
        with self._tx() as db:
            db.execute("insert or replace into tasks values (?,?,?,?,?,?,?,?,?,?,?)", self._task_row(task))

    @staticmethod
    def _task_row(t: TaskRecord) -> tuple[object, ...]:
        return (
            t.task_id,
            t.chat_id,
            t.project_id,
            t.project_folder,
            t.instruction,
            t.created_at.isoformat(),
            t.phase.value,
            t.pause_state.value,
            t.timeout_streak,
            t.history_len,
            int(t.transcript_saved),
        )

    def get_task(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            row = self._db.execute("select * from tasks where task_id = ?", (task_id,)).fetchone()
        return self._task(row) if row else None

    def open_tasks(self) -> list[TaskRecord]:
        with self._lock:
            rows = self._db.execute(
                "select * from tasks where phase not in ('completed','failed','canceled') order by created_at"
            ).fetchall()
        return [self._task(r) for r in rows]

    @staticmethod
    def _task(r: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            r["task_id"],
            r["chat_id"],
            r["project_id"],
            r["project_folder"],
            r["instruction"],
            _dt(r["created_at"]),
            TaskPhase(r["phase"]),
            PauseState(r["pause_state"]),
            r["timeout_streak"],
            r["history_len"],
            bool(r["transcript_saved"]),
        )

    # --- approvals ---------------------------------------------------------------------
    def insert_approval(self, a: Approval) -> None:
        with self._tx() as db:
            db.execute("insert into approvals values (?,?,?,?,?,?,?,?,?,?,?,?)", self._approval_row(a))

    def save_approval(self, a: Approval) -> None:
        with self._tx() as db:
            db.execute("insert or replace into approvals values (?,?,?,?,?,?,?,?,?,?,?,?)", self._approval_row(a))

    @staticmethod
    def _approval_row(a: Approval) -> tuple[object, ...]:
        return (
            a.approval_id,
            a.task_id,
            a.chat_id,
            a.call_key,
            a.tool,
            a.summary,
            json.dumps(a.arguments, default=str),
            a.created_at.isoformat(),
            a.expires_at.isoformat(),
            a.status.value,
            a.decision.value if a.decision else None,
            a.resolved_by,
        )

    def get_approval(self, approval_id: str) -> Approval | None:
        with self._lock:
            row = self._db.execute("select * from approvals where approval_id = ?", (approval_id,)).fetchone()
        return self._approval(row) if row else None

    def approval_for_call(self, key: str) -> Approval | None:
        with self._lock:
            row = self._db.execute(
                "select * from approvals where call_key = ? order by created_at desc limit 1", (key,)
            ).fetchone()
        return self._approval(row) if row else None

    def pending_approvals(self, task_id: str | None = None) -> list[Approval]:
        with self._lock:
            if task_id is None:
                rows = self._db.execute("select * from approvals where status = 'pending'").fetchall()
            else:
                rows = self._db.execute(
                    "select * from approvals where status = 'pending' and task_id = ?", (task_id,)
                ).fetchall()
        return [self._approval(r) for r in rows]

    def answer_approval(self, approval_id: str, decision: ApprovalDecision, by: str, now: datetime) -> Approval:
        """First answer wins. Raises ApprovalAlreadyResolved (or KeyError if unknown)."""
        with self._tx() as db:
            row = db.execute("select * from approvals where approval_id = ?", (approval_id,)).fetchone()
            if row is None:
                raise KeyError(approval_id)
            approval = self._approval(row)
            try:
                approval.answer(decision, by, now)
            finally:
                db.execute(
                    "update approvals set status = ?, decision = ?, resolved_by = ? where approval_id = ?",
                    (
                        approval.status.value,
                        approval.decision.value if approval.decision else None,
                        approval.resolved_by,
                        approval_id,
                    ),
                )
            if decision is ApprovalDecision.ALLOW_ALWAYS:
                db.execute(
                    "insert or ignore into allow_rules values (?,?,?)", (approval.chat_id, approval.tool, _now())
                )
            return approval

    @staticmethod
    def _approval(r: sqlite3.Row) -> Approval:
        return Approval(
            r["approval_id"],
            r["task_id"],
            r["chat_id"],
            r["call_key"],
            r["tool"],
            r["summary"],
            json.loads(r["arguments"]),
            _dt(r["created_at"]),
            _dt(r["expires_at"]),
            ApprovalStatus(r["status"]),
            ApprovalDecision(r["decision"]) if r["decision"] else None,
            r["resolved_by"],
        )

    # --- allow rules -------------------------------------------------------------------
    def rules_for_chat(self, chat_id: str) -> list[AllowRule]:
        with self._lock:
            rows = self._db.execute("select * from allow_rules where chat_id = ? order by tool", (chat_id,)).fetchall()
        return [AllowRule(r["chat_id"], r["tool"], _dt(r["created_at"])) for r in rows]

    def has_rule(self, chat_id: str, tool: str) -> bool:
        with self._lock:
            return (
                self._db.execute("select 1 from allow_rules where chat_id = ? and tool = ?", (chat_id, tool)).fetchone()
                is not None
            )

    def revoke_rule(self, chat_id: str, tool: str) -> bool:
        with self._tx() as db:
            return db.execute("delete from allow_rules where chat_id = ? and tool = ?", (chat_id, tool)).rowcount > 0

    # --- call marks --------------------------------------------------------------------
    def get_mark(self, key: str) -> CallMark | None:
        with self._lock:
            r = self._db.execute("select * from call_marks where key = ?", (key,)).fetchone()
        return (
            CallMark(r["key"], r["task_id"], r["tool"], MarkState(r["state"]), r["result"], bool(r["is_error"]))
            if r
            else None
        )

    def put_mark(self, mark: CallMark) -> None:
        with self._tx() as db:
            db.execute(
                "insert or replace into call_marks values (?,?,?,?,?,?)",
                (mark.key, mark.task_id, mark.tool, mark.state.value, mark.result, int(mark.is_error)),
            )

    # --- transcript --------------------------------------------------------------------
    def load_transcript(self, chat_id: str) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "select message from transcript where chat_id = ? order by id", (chat_id,)
            ).fetchall()
        return [json.loads(r["message"]) for r in rows]

    def append_transcript(self, chat_id: str, task_id: str, messages: list[dict]) -> None:
        with self._tx() as db:
            db.executemany(
                "insert into transcript (chat_id, task_id, message) values (?,?,?)",
                [(chat_id, task_id, json.dumps(m, default=str)) for m in messages],
            )
            db.execute("update tasks set transcript_saved = 1 where task_id = ?", (task_id,))

    def delete_chat(self, chat_id: str) -> list[str]:
        """Remove everything this service holds for a chat. Idempotent. Returns the chat's task ids."""
        with self._tx() as db:
            task_ids = [r[0] for r in db.execute("select task_id from tasks where chat_id = ?", (chat_id,))]
            for table in ("transcript", "allow_rules", "approvals", "tasks", "chat_summaries"):
                db.execute(f"delete from {table} where chat_id = ?", (chat_id,))  # noqa: S608 - fixed table names
            db.executemany("delete from call_marks where task_id = ?", [(t,) for t in task_ids])
        return task_ids

    # --- chat summaries (compaction) -----------------------------------------------------
    def chat_summary(self, chat_id: str) -> tuple[int, str] | None:
        with self._lock:
            r = self._db.execute("select upto, summary from chat_summaries where chat_id = ?", (chat_id,)).fetchone()
        return (r[0], r[1]) if r else None

    def save_chat_summary(self, chat_id: str, upto: int, summary: str) -> None:
        with self._tx() as db:
            db.execute("insert or replace into chat_summaries values (?,?,?,?)", (chat_id, upto, summary, _now()))

    # --- settings (non-secret, JSON) ------------------------------------------------------
    def get_setting(self, key: str) -> Any:
        with self._lock:
            r = self._db.execute("select value from settings where key = ?", (key,)).fetchone()
        return json.loads(r[0]) if r else None

    def set_setting(self, key: str, value: Any) -> None:
        with self._tx() as db:
            db.execute("insert or replace into settings values (?, ?)", (key, json.dumps(value)))

    # --- allow rules across all chats --------------------------------------------------------
    def all_rules(self) -> list[AllowRule]:
        with self._lock:
            rows = self._db.execute("select * from allow_rules order by chat_id, tool").fetchall()
        return [AllowRule(r["chat_id"], r["tool"], _dt(r["created_at"])) for r in rows]

    # --- prompts -----------------------------------------------------------------------
    def current_prompt(self) -> tuple[int, str] | None:
        with self._lock:
            r = self._db.execute("select version, text from prompts order by version desc limit 1").fetchone()
        return (r[0], r[1]) if r else None

    def save_prompt(self, text: str) -> int:
        with self._tx() as db:
            return int(
                db.execute("insert into prompts (text, created_at) values (?, ?)", (text, _now())).lastrowid or 0
            )

    def prompt_versions(self) -> list[tuple[int, str, str]]:
        with self._lock:
            return [
                (r[0], r[1], r[2])
                for r in self._db.execute("select version, created_at, text from prompts order by version desc")
            ]
