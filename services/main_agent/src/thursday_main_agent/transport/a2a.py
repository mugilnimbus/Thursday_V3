"""A2A surface of the main agent, built on the a2a-sdk (spike S1).

- The executor maps run outcomes to A2A states: approval -> INPUT_REQUIRED with an
  ApprovalRequest data part; pause -> WORKING with `pause_state` metadata; done ->
  result artifact and COMPLETED; failure -> FAILED.
- The ingress guard sits in front of the SDK dispatcher: service token, the task-control
  extension (PauseTask, ResumeTask), approval answers (first answer wins, checked before
  the SDK sees them), no extra messages to running tasks, project metadata on new tasks.
- Internal "kicks" (approval timeout, resume, recovery) enter through the SDK in process
  with a flag no remote caller can set.
- Pushes are filtered to terminal and input states.
"""

import json
import logging
import os
import uuid
from typing import Any

import httpx
from a2a.helpers.proto_helpers import get_data_parts, get_message_text, new_data_part, new_task_from_user_message
from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.context import ServerCallContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.request_handlers.default_request_handler_v2 import DefaultRequestHandlerV2
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.routes.jsonrpc_dispatcher import JsonRpcDispatcher
from a2a.server.tasks.base_push_notification_sender import BasePushNotificationSender
from a2a.server.tasks.database_push_notification_config_store import DatabasePushNotificationConfigStore
from a2a.server.tasks.database_task_store import DatabaseTaskStore
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types.a2a_pb2 import (
    AgentCapabilities,
    AgentCard,
    AgentExtension,
    AgentInterface,
    AgentSkill,
    HTTPAuthSecurityScheme,
    Message,
    Part,
    Role,
    SecurityScheme,
    SendMessageConfiguration,
    SendMessageRequest,
    Task,
    TaskState,
    TaskStatusUpdateEvent,
)
from google.protobuf.json_format import MessageToDict
from pydantic import SecretStr, ValidationError
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import BaseRoute, Route
from thursday_contracts.approvals import APPROVAL_ANSWER_KIND, ApprovalAnswer
from thursday_contracts.task_control import (
    EXTENSIONS_HEADER,
    PAUSE_TASK_METHOD,
    RESUME_TASK_METHOD,
    TASK_CONTROL_EXTENSION_URI,
    TASK_NOT_FOUND_CODE,
    TASK_NOT_PAUSABLE_CODE,
    TaskControlResult,
)

from thursday_main_agent.application.runner import RunOutcome
from thursday_main_agent.application.tasks import TaskService, UnknownTask, clip_result
from thursday_main_agent.domain.approvals import ApprovalAlreadyResolved
from thursday_main_agent.domain.tasks import TaskNotControllable
from thursday_main_agent.infrastructure.store import Store

log = logging.getLogger(__name__)
INTERNAL_KIND = "thursday.internal"
INTERNAL_FLAG = "thursday_internal"
META_PROJECT_ID = "thursday.project_id"
META_PROJECT_FOLDER = "thursday.project_folder"
META_ANSWERED_BY = "thursday.answered_by"
APPROVAL_ALREADY_RESOLVED_CODE = -32041
UNSUPPORTED_OPERATION_CODE = -32004
INVALID_PARAMS_CODE = -32602
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
    def __init__(self, service: TaskService, store: Store) -> None:
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
            self._service.create(
                task.id, task.context_id, meta[META_PROJECT_ID], meta[META_PROJECT_FOLDER], instruction
            )
            updater = TaskUpdater(event_queue, task.id, task.context_id)
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


def rpc_error(request_id: object, code: int, message: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


class A2AServer:
    def __init__(
        self, service: TaskService, store: Store, db_url: str, base_url: str, token: SecretStr, version: str
    ) -> None:
        self._service = service
        self._store = store
        self._token = token.get_secret_value()
        engine = create_async_engine(db_url)
        owner = lambda _ctx: "thursday"  # noqa: E731 - one owner: the gateway and the voice agent share tasks
        self.task_store = DatabaseTaskStore(engine, owner_resolver=owner)
        self.push_store = DatabasePushNotificationConfigStore(engine, owner_resolver=owner)
        self._push_client = httpx.AsyncClient(timeout=5)
        self.card = AgentCard(
            name="thursday-main-agent",
            version=version,
            description="Carries out tasks on the PC inside a project folder, with tools and user approvals.",
            supported_interfaces=[
                AgentInterface(url=f"{base_url}/a2a", protocol_binding="JSONRPC", protocol_version="1.0")
            ],
            capabilities=AgentCapabilities(
                streaming=True,
                push_notifications=True,
                extensions=[AgentExtension(uri=TASK_CONTROL_EXTENSION_URI, description="PauseTask and ResumeTask")],
            ),
            security_schemes={
                "bearer": SecurityScheme(http_auth_security_scheme=HTTPAuthSecurityScheme(scheme="bearer"))
            },
            default_input_modes=["text/plain", "application/json"],
            default_output_modes=["text/plain"],
            skills=[
                AgentSkill(
                    id="run-task",
                    name="Run a task",
                    tags=["pc", "files", "shell"],
                    description="Carry out an instruction in the project folder with tools.",
                )
            ],
        )
        self.handler = DefaultRequestHandlerV2(
            MainAgentExecutor(service, store),
            self.task_store,
            self.card,
            push_config_store=self.push_store,
            push_sender=RelevantPushSender(self._push_client, self.push_store),
        )
        self._dispatcher = JsonRpcDispatcher(request_handler=self.handler)

    async def initialize(self) -> None:
        await self.task_store.initialize()
        await self.push_store.initialize()

    def routes(self) -> list[BaseRoute]:
        return [Route("/a2a", self._rpc, methods=["POST"]), *create_agent_card_routes(self.card)]

    async def kick(self, task_id: str, data: dict[str, Any]) -> None:
        record = self._store.get_task(task_id)
        if record is None:
            raise UnknownTask(task_id)
        message = Message(
            role=Role.ROLE_USER,
            message_id=str(uuid.uuid4()),
            task_id=task_id,
            context_id=record.chat_id,
            parts=[new_data_part({"kind": INTERNAL_KIND, **data})],
        )
        request = SendMessageRequest(message=message, configuration=SendMessageConfiguration(return_immediately=True))
        context = ServerCallContext(state={INTERNAL_FLAG: True, "headers": {"A2A-Version": "1.0"}})
        await self.handler.on_message_send(request, context)

    async def aclose(self) -> None:
        await self.handler.aclose()
        await self._push_client.aclose()

    # --- ingress guard -------------------------------------------------------------------
    async def _rpc(self, request: Request) -> JSONResponse:
        header = request.headers.get("authorization", "")
        if not self._token or header != f"Bearer {self._token}":
            return JSONResponse({"error": "unauthenticated"}, status_code=401)
        try:
            body = json.loads(await request.body())
        except ValueError:
            return rpc_error(None, -32700, "parse error")
        if not isinstance(body, dict):
            return rpc_error(None, -32600, "batch requests are not supported")
        request_id, method, params = body.get("id"), body.get("method"), body.get("params") or {}
        if method in (PAUSE_TASK_METHOD, RESUME_TASK_METHOD):
            return await self._task_control(request, request_id, method, params)
        if method in ("SendMessage", "SendStreamingMessage"):
            refusal = self._check_message(request_id, params.get("message") or {})
            if refusal is not None:
                return refusal
        return await self._dispatcher.handle_requests(request)  # pyright: ignore[reportReturnType]

    async def _task_control(self, request: Request, request_id: object, method: str, params: dict) -> JSONResponse:
        if TASK_CONTROL_EXTENSION_URI not in request.headers.get(EXTENSIONS_HEADER, ""):
            return rpc_error(request_id, -32601, "task-control extension not activated")
        task_id = str(params.get("id", ""))
        try:
            if method == PAUSE_TASK_METHOD:
                state = self._service.pause(task_id)
            else:
                state, wake = self._service.resume(task_id)
                if wake:
                    await self.kick(task_id, {"action": "resume"})
        except UnknownTask:
            return rpc_error(request_id, TASK_NOT_FOUND_CODE, "task not found")
        except TaskNotControllable as exc:
            return rpc_error(request_id, TASK_NOT_PAUSABLE_CODE, str(exc))
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": TaskControlResult(id=task_id, pause_state=state).model_dump(mode="json"),
            }
        )

    def _check_message(self, request_id: object, message: dict[str, Any]) -> JSONResponse | None:
        data_parts = [
            p["data"] for p in message.get("parts", []) if isinstance(p, dict) and isinstance(p.get("data"), dict)
        ]
        if any(d.get("kind") == INTERNAL_KIND for d in data_parts):
            return rpc_error(request_id, INVALID_PARAMS_CODE, "internal messages cannot be sent from outside")
        task_id = message.get("taskId")
        if task_id:
            answer = next((d for d in data_parts if d.get("kind") == APPROVAL_ANSWER_KIND), None)
            if answer is None:
                return rpc_error(
                    request_id,
                    UNSUPPORTED_OPERATION_CODE,
                    "this task is running; stop it and send a new task to change it",
                )
            try:
                parsed = ApprovalAnswer.model_validate(answer)
            except ValidationError:
                return rpc_error(request_id, INVALID_PARAMS_CODE, "invalid approval answer")
            approval = self._store.get_approval(parsed.approval_id)
            if approval is None or approval.task_id != task_id:
                return rpc_error(request_id, TASK_NOT_FOUND_CODE, "approval not found for this task")
            by = str((message.get("metadata") or {}).get(META_ANSWERED_BY, "client"))[:40]
            try:
                self._service.answer_approval(parsed.approval_id, parsed.decision, by)
            except ApprovalAlreadyResolved as exc:
                return rpc_error(
                    request_id, APPROVAL_ALREADY_RESOLVED_CODE, f"approval already resolved ({exc.status})"
                )
            return None
        meta = message.get("metadata") or {}
        folder = meta.get(META_PROJECT_FOLDER)
        if not message.get("contextId") or not meta.get(META_PROJECT_ID) or not isinstance(folder, str):
            return rpc_error(
                request_id,
                INVALID_PARAMS_CODE,
                f"new tasks need contextId and metadata {META_PROJECT_ID} and {META_PROJECT_FOLDER}",
            )
        if not os.path.isabs(folder) or not os.path.isdir(folder):
            return rpc_error(request_id, INVALID_PARAMS_CODE, "project folder does not exist")
        return None
