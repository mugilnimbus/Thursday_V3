"""The read model: what the agents' events add up to (tasks, approvals, notifications, messages).

It is a projection, so it can be rebuilt from the agents' replay endpoints. The store calls this for
every event it accepts; nothing else writes these tables, except a client marking a notification read.
"""

import json
import sqlite3

from thursday_contracts.events import EventEnvelope, EventType


def project_event(db: sqlite3.Connection, pos: int, e: EventEnvelope) -> None:
    """Apply one accepted event, at its position in the log, in the transaction that stored it."""
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
        # A voice agent stopped mid-answer publishes the user message again when it retries the turn.
        # The event log keeps both events; the chat shows the message once.
        if (
            role == "user"
            and client_id
            and db.execute(
                "select 1 from messages where chat_id = ? and role = 'user' and client_message_id = ?",
                (e.chat_id, client_id),
            ).fetchone()
        ):
            return
        db.execute(
            "insert into messages (chat_id, role, text, client_message_id, pos, created_at, direct) "
            "values (?,?,?,?,?,?,?)",
            (
                e.chat_id,
                role,
                str(p.get("text", "")),
                client_id,
                pos,
                ts,
                int(role == "user" and bool(p.get("direct"))),
            ),
        )
