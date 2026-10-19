"""What the A2A SDK runs for a task, and which of its updates are pushed to the voice agent.

- The executor maps run outcomes to A2A states: approval -> INPUT_REQUIRED with an
  ApprovalRequest data part; pause -> WORKING with `pause_state` metadata; done ->
  result artifact and COMPLETED; failure -> FAILED.
- Pushes are filtered to terminal and input states.
"""

import uuid
from typing import Any

from a2a.helpers.proto_helpers import get_data_parts, get_message_text, new_data_part, new_task_from_user_message
from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks.base_push_notification_sender import BasePushNotificationSender
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types.a2a_pb2 import Message, Part, Role, Task, TaskState, TaskStatusUpdateEvent
from google.protobuf.json_format import MessageToDict

from thursday_main_agent.application.ports import TaskLookup
from thursday_main_agent.application.runner import RunOutcome
from thursday_main_agent.application.tasks import TaskService, clip_result
from thursday_main_agent.domain.tasks import DuplicateRequest

INTERNAL_KIND = "thursday.internal"
INTERNAL_FLAG = "thursday_internal"
META_PROJECT_ID = "thursday.project_id"
META_PROJECT_FOLDER = "thursday.project_folder"
META_REQUEST = "thursday.request"
"""Optional metadata of a new task's message: the name of the request. One task is started per name; the same
request sent again (its first answer was lost on the way) is answered with the task already started."""
PUSH_STATES = {
    TaskState.TASK_STATE_COMPLETED,
    TaskState.TASK_STATE_FAILED,
    TaskState.TASK_STATE_CANCELED,
    TaskState.TASK_STATE_REJECTED,
    TaskState.TASK_STATE_INPUT_REQUIRED,
    TaskState.TASK_STATE_AUTH_REQUIRED,
}


def agent_message(task_id: str, context_id: str, text: str, data: dict[str, Any] | None = None) -> Message:
    parts = [Part(text=text)]
    if data is not None:
        parts.append(new_data_part(data))
    return Message(
        role=Role.ROLE_AGENT, message_id=str(uuid.uuid4()), task_id=task_id, context_id=context_id, parts=parts
    )


class MainAgentExecutor(AgentExecutor):
    def __init__(self, service: TaskService, store: TaskLookup) -> None:
        self._service = service
        self._store = store

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        message = context.message
        assert message is not None
        current = context.current_task
        if current is None:
            task = new_task_from_user_message(message)
            await event_queue.enqueue_event(task)
            meta = MessageToDict(message.metadata) if message.HasField("metadata") else {}
            instruction = get_message_text(message)
            updater = TaskUpdater(event_queue, task.id, task.context_id)
            try:
                self._service.create(
                    task.id,
                    task.context_id,
                    meta[META_PROJECT_ID],
                    meta[META_PROJECT_FOLDER],
                    instruction,
                    meta.get(META_REQUEST) or None,
                )
            except DuplicateRequest as exc:
                # The same request arrived twice at the same moment, so the check at the door let both in. The
                # first one has the task; this one ends here, so the work is not done twice.
                await updater.failed(agent_message(task.id, task.context_id, f"Nothing was started: {exc}."))
                return
            await updater.start_work()
            outcome = await self._service.drive(task.id, instruction=instruction)
        else:
            updater = TaskUpdater(event_queue, current.id, current.context_id)
            record = self._store.get_task(current.id)
            if record is None:
                await updater.failed(
                    agent_message(current.id, current.context_id, "This task is unknown to the agent.")
                )
                return
            data = next(iter(get_data_parts(message.parts)), {}) or {}
            internal = context.call_context.state.get(INTERNAL_FLAG) is True and data.get("kind") == INTERNAL_KIND
            await updater.start_work()
            if internal and data.get("action") == "start":
                outcome = await self._service.drive(current.id, instruction=record.instruction)
            elif internal and data.get("action") == "recover":
                outcome = await self._service.drive(current.id)
            else:
                outcome = await self._service.drive(current.id, resume={"reason": data.get("action") or "answer"})
        await self._publish(outcome, updater)

    async def _publish(self, outcome: RunOutcome, updater: TaskUpdater) -> None:
        task_id, context_id = updater.task_id, updater.context_id
        if outcome.kind == "needs_approval" and outcome.approval is not None:
            a = outcome.approval
            data = {
                "kind": "thursday.approval_request",
                "approval_id": a.approval_id,
                "task_id": a.task_id,
                "chat_id": a.chat_id,
                "tool": a.tool,
                "summary": a.summary,
                "arguments": a.arguments,
                "expires_at": a.expires_at.isoformat(),
            }
            await updater.requires_input(agent_message(task_id, context_id, f"Approval needed: {a.summary}", data))
        elif outcome.kind == "paused":
            await updater.update_status(TaskState.TASK_STATE_WORKING, metadata={"pause_state": "paused"})
        elif outcome.kind == "completed":
            await updater.add_artifact([Part(text=outcome.text or "Done.")], name="result")
            await updater.complete(agent_message(task_id, context_id, clip_result(outcome.text or "Done.")))
        else:
            await updater.failed(agent_message(task_id, context_id, outcome.text or "The task failed."))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        assert task is not None
        await self._service.canceled(task.id)
        await TaskUpdater(event_queue, task.id, task.context_id).cancel(
            agent_message(task.id, task.context_id, "Stopped by the user.")
        )


class RelevantPushSender(BasePushNotificationSender):
    """Push only what the voice agent acts on: terminal and input-required states."""

    async def send_notification(self, task_id: str, event: Any) -> None:
        if isinstance(event, (Task, TaskStatusUpdateEvent)):
            state = event.status.state
        else:
            return
        if state in PUSH_STATES:
            await super().send_notification(task_id, event)
