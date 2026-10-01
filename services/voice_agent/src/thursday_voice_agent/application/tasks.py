"""Delegated tasks: start them, control them, and turn their updates into short spoken messages."""

import logging
import secrets
from typing import Any

from langchain_core.messages import AIMessage, messages_to_dict
from thursday_contracts.approvals import ApprovalDecision
from thursday_contracts.events import EventType
from thursday_runtime.outbox import EventPublisher

from thursday_voice_agent.infrastructure.main_agent import MainAgentClient, MainAgentRefused, MainAgentUnavailable
from thursday_voice_agent.infrastructure.store import DelegatedTask, Store

log = logging.getLogger(__name__)
ALREADY_RESOLVED = -32041


def state_name(raw: str) -> str:
    return raw.removeprefix("TASK_STATE_").lower()


def parts_of(status: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    parts = (status.get("message") or {}).get("parts") or []
    text = " ".join(p["text"] for p in parts if isinstance(p.get("text"), str)).strip()
    data = next((p["data"] for p in parts if isinstance(p.get("data"), dict)), None)
    return text, data


class TaskRelay:
    def __init__(self, store: Store, main: MainAgentClient, events: EventPublisher, push_url: str) -> None:
        self._store = store
        self._main = main
        self._events = events
        self._push_url = push_url

    async def delegate(self, chat_id: str, project_id: str, folder: str, instruction: str) -> DelegatedTask:
        token = secrets.token_urlsafe(24)
        task = await self._main.start_task(chat_id, instruction, project_id, folder, self._push_url, token)
        record = DelegatedTask(
            task["id"], chat_id, project_id, instruction, state_name(task["status"]["state"]), "", token, None, None
        )
        self._store.add_task(record)
        self._events.publish(
            EventType.DELEGATION,
            {"instruction": instruction, "by": "voice"},
            project_id=project_id,
            chat_id=chat_id,
            task_id=record.task_id,
        )
        return record

    def target(self, chat_id: str, task_id: str | None) -> DelegatedTask | None:
        if task_id:
            task = self._store.task(task_id)
            return task if task is not None and task.chat_id == chat_id else None
        open_tasks = self._store.tasks_for_chat(chat_id, open_only=True)
        return open_tasks[0] if open_tasks else None

    async def control(self, chat_id: str, action: str, task_id: str | None) -> str:
        task = self.target(chat_id, task_id)
        if task is None:
            return "There is no running task to " + action + "."
        handler = {"pause": self._main.pause, "resume": self._main.resume, "stop": self._main.cancel}[action]
        try:
            await handler(task.task_id)
        except MainAgentUnavailable:
            return "The main agent is not reachable right now."
        except MainAgentRefused as exc:
            return f"Could not {action} the task: {exc}"
        if action == "stop":
            self._store.update_task(task.task_id, "canceled", clear_approval=True)
        return {"pause": "Pausing after the current step.", "resume": "Resumed.", "stop": "Stopped."}[action]

    def describe(self, chat_id: str) -> str:
        tasks = self._store.tasks_for_chat(chat_id)[:5]
        if not tasks:
            return "No tasks in this chat yet."
        return "\n".join(
            f"{t.task_id[:8]}: {t.state}; {t.instruction[:80]}" + (f"; result: {t.summary[:160]}" if t.summary else "")
            for t in tasks
        )

    async def answer_spoken(self, chat_id: str, task: DelegatedTask, decision: ApprovalDecision) -> str:
        """Answer from a recognised spoken phrase (code path, not the model)."""
        assert task.approval_id is not None
        try:
            await self._main.answer(task.task_id, chat_id, task.approval_id, decision.value)
        except MainAgentUnavailable:
            return "I could not reach the main agent to pass that on."
        except MainAgentRefused as exc:
            if exc.code == ALREADY_RESOLVED:
                self._store.update_task(task.task_id, "working", clear_approval=True)
                return "That request was already answered."
            return f"That answer was not accepted: {exc}"
        self._store.update_task(task.task_id, "working", clear_approval=True)
        return {
            ApprovalDecision.ALLOW_ONCE: "Okay, allowed.",
            ApprovalDecision.ALLOW_ALWAYS: "Okay, allowed for the rest of this chat.",
            ApprovalDecision.DENY: "Okay, I told it no.",
        }[decision]

    def apply(self, task_json: dict[str, Any]) -> str | None:
        """Apply a pushed or fetched task state. Returns what to say, if anything."""
        task_id = task_json.get("id") or task_json.get("taskId")
        record = self._store.task(task_id) if task_id else None
        if record is None:
            return None
        status = task_json.get("status") or {}
        state = state_name(status.get("state", ""))
        text, data = parts_of(status)
        if state == record.state and state != "input_required":
            return None
        if state == "input_required" and data and data.get("approval_id"):
            if data["approval_id"] == record.approval_id:
                return None
            summary = str(data.get("summary", "an action"))
            self._store.update_task(record.task_id, state, approval=(data["approval_id"], summary))
            return f"The main agent needs your approval: {summary}. Say yes, always, or no."
        if state == "completed":
            self._store.update_task(record.task_id, state, summary=text, clear_approval=True)
            return f"Done. {text}" if text else "Done."
        if state == "failed":
            self._store.update_task(record.task_id, state, summary=text, clear_approval=True)
            return f"The task failed. {text}".strip()
        if state == "canceled":
            already = record.state == "canceled"
            self._store.update_task(record.task_id, state, clear_approval=True)
            return None if already else "The task was stopped."
        self._store.update_task(record.task_id, state)
        return None

    def say(self, chat_id: str, text: str) -> None:
        """A proactive spoken message: into the transcript and out as a chat message event."""
        self._store.append(chat_id, messages_to_dict([AIMessage(text)]))
        task = next(iter(self._store.tasks_for_chat(chat_id)), None)
        self._events.publish(
            EventType.ASSISTANT_MESSAGE,
            {"text": text, "spoken": True},
            chat_id=chat_id,
            project_id=task.project_id if task else None,
        )

    def push_token_ok(self, task_id: str, token: str | None) -> bool:
        record = self._store.task(task_id)
        return record is not None and token is not None and secrets.compare_digest(record.push_token, token)

    async def reconcile(self) -> None:
        """After a restart: catch up on tasks that changed while this agent was down."""
        for record in self._store.open_tasks():
            try:
                task = await self._main.get_task(record.task_id)
            except (MainAgentUnavailable, MainAgentRefused) as exc:
                log.info("cannot reconcile %s yet: %s", record.task_id, exc)
                continue
            spoken = self.apply(task)
            if spoken:
                self.say(record.chat_id, spoken)
