"""Delegated tasks: start them, control them, and turn their updates into short spoken messages."""

import asyncio
import base64
import hashlib
import hmac
import logging
import secrets
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.messages import AIMessage, messages_to_dict
from thursday_contracts.approvals import ApprovalDecision
from thursday_contracts.events import EventType

from thursday_voice_agent.application.errors import MainAgentRefused, MainAgentUnavailable
from thursday_voice_agent.application.ports import Events, MainAgent, TaskRecords
from thursday_voice_agent.domain.tasks import DelegatedTask

log = logging.getLogger(__name__)
ALREADY_RESOLVED = -32041
Reporter = Callable[[DelegatedTask], Awaitable[str | None]]


def state_name(raw: str) -> str:
    return raw.removeprefix("TASK_STATE_").lower()


def parts_of(status: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    parts = (status.get("message") or {}).get("parts") or []
    text = " ".join(p["text"] for p in parts if isinstance(p.get("text"), str)).strip()
    data = next((p["data"] for p in parts if isinstance(p.get("data"), dict)), None)
    return text, data


class TaskRelay:
    def __init__(
        self, store: TaskRecords, main: MainAgent, events: Events, push_url: str, push_secret: str = ""
    ) -> None:
        self._store = store
        self._main = main
        self._events = events
        self._push_url = push_url
        self._push_secret = push_secret
        self._reporter: Reporter | None = None
        self._background: set[asyncio.Task[None]] = set()

    def set_reporter(self, reporter: Reporter) -> None:
        """How a finished direct task is put into words (the voice model); set once the conversation exists."""
        self._reporter = reporter

    async def delegate(
        self,
        chat_id: str,
        project_id: str,
        folder: str,
        instruction: str,
        *,
        direct: bool = False,
        before_announced: Callable[[], None] | None = None,
        request: str | None = None,
    ) -> DelegatedTask:
        """Start the task. `before_announced` runs once the main agent has accepted it and before the delegation is
        published, so a caller can publish the user's message first and the chat reads in order.

        `request` names the request (see `request_name`). If the main agent started the task but its answer was
        lost, the request is sent again under the same name and the main agent gives that task back, so the work
        is not done twice."""
        token = self._push_token(request)
        task = await self._main.start_task(chat_id, instruction, project_id, folder, self._push_url, token, request)
        known = self._store.task(task["id"]) is not None  # this request was sent before, and it got this far then
        record = DelegatedTask(
            task["id"],
            chat_id,
            project_id,
            instruction,
            state_name(task["status"]["state"]),
            "",
            token,
            None,
            None,
            direct,
        )
        self._store.add_task(record)
        if before_announced is not None:
            before_announced()
        if not known:
            self._events.publish(
                EventType.DELEGATION,
                {"instruction": instruction, "by": "direct" if direct else "voice"},
                project_id=project_id,
                chat_id=chat_id,
                task_id=record.task_id,
            )
        return record

    def _push_token(self, request: str | None) -> str:
        """The secret the main agent sends back with a task's updates. The main agent keeps the one it was given
        first, so a request sent again has to carry the same one: for a named request it is worked out from the
        name with this service's own secret, not drawn at random."""
        if request is None or not self._push_secret:
            return secrets.token_urlsafe(24)
        digest = hmac.new(self._push_secret.encode(), request.encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")

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
        """A proactive spoken message: into the transcript and out as a chat message event. Nothing is said into a
        chat that was deleted in the meantime (a task's report can arrive after its chat is gone)."""
        if self._store.chat_deleted(chat_id):
            return
        self._store.append(chat_id, messages_to_dict([AIMessage(text)]))
        task = next(iter(self._store.tasks_for_chat(chat_id)), None)
        self._events.publish(
            EventType.ASSISTANT_MESSAGE,
            {"text": text, "spoken": True},
            chat_id=chat_id,
            project_id=task.project_id if task else None,
        )

    def announce(self, task_id: str, spoken: str) -> None:
        """Say what `apply` returned. A direct task that finished with a result is reported by the voice model in the
        background; everything else, and any report the model cannot give, is the plain message."""
        record = self._store.task(task_id)
        if record is None:
            return
        if record.direct and record.state == "completed" and record.summary.strip() and self._reporter is not None:
            job = asyncio.get_running_loop().create_task(self._report(record, spoken))
            self._background.add(job)
            job.add_done_callback(self._background.discard)
        else:
            self.say(record.chat_id, spoken)

    async def _report(self, record: DelegatedTask, fallback: str) -> None:
        reporter = self._reporter
        assert reporter is not None
        try:
            text = await reporter(record) or fallback
        except asyncio.CancelledError:
            self.say(record.chat_id, fallback)  # the service is stopping: the user still gets the result
            raise
        except Exception:
            log.exception("the voice model could not report task %s", record.task_id)
            text = fallback
        self.say(record.chat_id, text)

    async def close(self) -> None:
        for job in list(self._background):
            job.cancel()
        await asyncio.gather(*self._background, return_exceptions=True)

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
                self.announce(record.task_id, spoken)
