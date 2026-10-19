"""What clients ask about the read model: the event log, messages, tasks, approvals, notifications.

Every query the HTTP layer needs is a method here, so no SQL is written outside the storage layer.
Read-only, except that a client may mark a notification as read.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from thursday_gateway.domain.model import Outgoing, Project
from thursday_gateway.infrastructure.store import Store


def _containing(text: str) -> str:
    """A LIKE pattern for rows that contain the text as typed (`%`, `_` and `\\` stand for themselves)."""
    return "%" + text.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"


class ReadModel:
    def __init__(self, store: Store) -> None:
        self._store = store

    # --- projects, chats and the message queue (the gateway's own records) ---------------
    def projects(self) -> list[Project]:
        return self._store.projects()

    def chats(self, project_id: str) -> list[dict[str, Any]]:
        return self._store.chats(project_id)

    def chat_titles(self) -> dict[str, str]:
        return self._store.chat_titles()

    def pending_outgoing(self, chat_id: str) -> list[Outgoing]:
        return self._store.pending_outgoing(chat_id)

    def queued_count(self) -> int:
        return self._store.queued_count()

    # --- the event log -------------------------------------------------------------------
    def stream_position(self) -> int:
        """The position of the newest stored event: where a client joins the live stream."""
        return self._store.last_pos()

    def events_after(self, pos: int, limit: int, chat_id: str | None = None) -> list[dict[str, Any]]:
        if chat_id is None:
            rows = self._store.query("select * from events where pos > ? order by pos limit ?", (pos, limit))
        else:
            rows = self._store.query(
                "select * from events where chat_id = ? and pos > ? order by pos limit ?", (chat_id, pos, limit)
            )
        return [dict(r) for r in rows]

    def task_events(self, task_id: str, limit: int = 2000) -> tuple[list[dict[str, Any]], int]:
        """A task's events in order, and how many were left out of the middle.

        A very long task is cut in the middle, never at the end: the first half of the limit and the last
        half are returned, so how it started and how it ended are always there.
        """
        total = int(self._store.query("select count(*) as n from events where task_id = ?", (task_id,))[0]["n"])
        if total <= limit:
            rows = self._store.query("select * from events where task_id = ? order by pos", (task_id,))
            return [dict(r) for r in rows], 0
        head = limit // 2
        tail = limit - head
        first = self._store.query("select * from events where task_id = ? order by pos limit ?", (task_id, head))
        last = self._store.query(
            "select * from (select * from events where task_id = ? order by pos desc limit ?) order by pos",
            (task_id, tail),
        )
        return [dict(r) for r in (*first, *last)], total - limit

    def llm_calls(self, since: timedelta, limit: int = 2000) -> list[dict[str, Any]]:
        """Successful model calls in the period, oldest first: when, which agent, speed, and context use."""
        cutoff = (datetime.now(UTC) - since).isoformat()
        rows = self._store.query(
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

    # --- messages ------------------------------------------------------------------------
    def messages(self, chat_id: str, before: int | None, limit: int) -> list[dict[str, Any]]:
        """The newest messages of a chat older than `before`, oldest first."""
        rows = self._store.query(
            "select * from messages where chat_id = ? and id < ? order by id desc limit ?",
            (chat_id, before or 2**62, limit),
        )
        return [dict(r) for r in reversed(rows)]

    def search_messages(self, text: str, limit: int) -> list[dict[str, Any]]:
        """Messages in active chats that contain the text, newest first, with the chat's title and project."""
        rows = self._store.query(
            "select m.*, c.title, c.project_id from messages m join chats c using (chat_id) "
            "where c.state = 'active' and m.text like ? escape '\\' order by m.id desc limit ?",
            (_containing(text), limit),
        )
        return [dict(r) for r in rows]

    # --- tasks ---------------------------------------------------------------------------
    def task(self, task_id: str) -> dict[str, Any] | None:
        rows = self._store.query("select * from tasks where task_id = ?", (task_id,))
        return dict(rows[0]) if rows else None

    def chat_tasks(self, chat_id: str) -> list[dict[str, Any]]:
        rows = self._store.query("select * from tasks where chat_id = ? order by created_at desc limit 100", (chat_id,))
        return [dict(t) for t in rows]

    def find_tasks(self, state: str, text: str | None, limit: int) -> list[dict[str, Any]]:
        """Tasks of every chat, newest first, with chat and project names. `state` is all, running or failed."""
        sql = (
            "select t.*, c.title as chat_title, p.name as project_name from tasks t "
            "left join chats c on c.chat_id = t.chat_id left join projects p on p.project_id = t.project_id where 1=1"
        )
        params: list[Any] = []
        if state == "running":
            sql += " and t.state in ('submitted','working','input_required')"
        elif state == "failed":
            sql += " and t.state = 'failed'"
        if text:
            sql += " and (t.instruction like ? escape '\\' or t.summary like ? escape '\\')"
            params += [_containing(text), _containing(text)]
        rows = self._store.query(sql + " order by t.created_at desc limit ?", (*params, limit))
        return [dict(row) for row in rows]

    # --- approvals -----------------------------------------------------------------------
    def approval(self, approval_id: str) -> dict[str, Any] | None:
        rows = self._store.query("select * from approvals where approval_id = ?", (approval_id,))
        return dict(rows[0]) if rows else None

    def pending_approvals(self, chat_id: str | None = None) -> list[dict[str, Any]]:
        """Approvals still waiting for an answer, oldest first; of one chat, or of all."""
        # Only fixed fragments are concatenated; values are bound parameters.
        sql = "select * from approvals where status = 'pending'" + (" and chat_id = ?" if chat_id else "")  # noqa: S608
        rows = self._store.query(sql + " order by requested_at", (chat_id,) if chat_id else ())
        return [{**dict(a), "arguments": json.loads(a["arguments"])} for a in rows]

    def pending_approval_count(self) -> int:
        return int(self._store.query("select count(*) as n from approvals where status = 'pending'")[0]["n"])

    # --- notifications -------------------------------------------------------------------
    def notifications(self, unread: bool, limit: int) -> list[dict[str, Any]]:
        rows = self._store.query(
            "select * from notifications" + (" where read = 0" if unread else "") + " order by id desc limit ?",  # noqa: S608
            (limit,),
        )
        return [dict(n) for n in rows]

    def mark_notification_read(self, notification_id: int) -> None:
        with self._store.tx() as db:
            db.execute("update notifications set read = 1 where id = ?", (notification_id,))
