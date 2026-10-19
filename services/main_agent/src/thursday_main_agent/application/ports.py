"""What the main agent's logic needs from storage, the tool servers and the gateway link, as interfaces ("ports").

Each one lists only what its user calls. `infrastructure` holds the classes that fit them, and only `bootstrap`
knows which class sits behind which port. They are structural: a class fits by having the methods.
"""

from datetime import datetime, timedelta
from typing import Any, Protocol

from mcp_types import CallToolResult, InputRequiredResult, Tool
from thursday_contracts.approvals import ApprovalDecision
from thursday_contracts.events import EventType

from thursday_main_agent.domain.approvals import AllowRule, Approval
from thursday_main_agent.domain.tasks import TaskRecord
from thursday_main_agent.domain.tool_calls import CallMark

# --- what goes out and what runs tools -------------------------------------------------------------


class Events(Protocol):
    def publish(
        self,
        type_: EventType,
        payload: dict[str, Any],
        *,
        project_id: str | None = None,
        chat_id: str | None = None,
        task_id: str | None = None,
    ) -> int: ...


class ToolServers(Protocol):
    async def list_tools(self, project_id: str, folder: str) -> list[Tool]: ...

    async def call(
        self,
        project_id: str,
        folder: str,
        name: str,
        arguments: dict[str, Any],
        *,
        input_responses: dict[str, Any] | None = None,
        request_state: str | None = None,
        chat_id: str | None = None,
    ) -> CallToolResult | InputRequiredResult:
        """`chat_id` travels beside the arguments, so the tool server can record whose call it was."""
        ...


class ToolServerControl(Protocol):
    async def stop_project(self, project_id: str) -> bool: ...

    def status(self) -> dict[str, dict[str, object]]: ...


class Outbox(Protocol):
    """This service's stored events: the ones still to send, and the sent ones kept for replay."""

    def after(self, seq: int, limit: int) -> list[dict[str, Any]]: ...

    def forget(self, *, chat_id: str | None = None, project_id: str | None = None) -> int: ...

    def prune_sent(self, older_than: timedelta) -> int: ...

    def backlog(self) -> int: ...


class GatewayLink(Protocol):
    @property
    def gateway_reachable(self) -> bool: ...


class TaskProtocolRecords(Protocol):
    """What the task protocol (A2A) keeps about a task on its own."""

    async def forget(self, task_id: str) -> None: ...


class ToolCallLogs(Protocol):
    """The tool server's own call logs. They are its data: this service can only ask it to forget."""

    async def forget_chat(self, chat_id: str) -> int: ...

    async def forget_project(self, project_id: str) -> list[str]: ...


# --- the main agent's own records ----------------------------------------------------------------


class RunnerRecords(Protocol):
    """What the loop reads and writes around each model call."""

    def get_task(self, task_id: str) -> TaskRecord | None: ...

    def save_task(self, task: TaskRecord) -> None: ...

    def load_transcript(self, chat_id: str) -> list[dict]: ...

    def chat_summary(self, chat_id: str) -> tuple[int, str] | None: ...

    def save_chat_summary(self, chat_id: str, upto: int, summary: str) -> None: ...

    def get_approval(self, approval_id: str) -> Approval | None: ...


class ToolCallRecords(Protocol):
    """Run-once marks, approvals and allow-always rules, for one tool call."""

    def get_mark(self, key: str) -> CallMark | None: ...

    def put_mark(self, mark: CallMark) -> None: ...

    def approval_for_call(self, key: str) -> Approval | None: ...

    def get_approval(self, approval_id: str) -> Approval | None: ...

    def insert_approval(self, a: Approval) -> None: ...

    def has_rule(self, chat_id: str, tool: str) -> bool: ...


class LoopRecords(RunnerRecords, ToolCallRecords, Protocol):
    """Everything the task runner and its tool step need together."""


class TaskRecords(Protocol):
    """Tasks through their life: created, driven, answered, finished."""

    def get_task(self, task_id: str) -> TaskRecord | None: ...

    def insert_task(self, task: TaskRecord, request: str | None = None) -> None:
        """Raises `DuplicateRequest` when a task was already started under the request name."""
        ...

    def save_task(self, task: TaskRecord) -> None: ...

    def open_tasks(self) -> list[TaskRecord]: ...

    def append_transcript(self, chat_id: str, task_id: str, messages: list[dict]) -> None: ...

    def save_chat_summary(self, chat_id: str, upto: int, summary: str) -> None: ...

    def pending_approvals(self, task_id: str | None = None) -> list[Approval]: ...

    def save_approval(self, a: Approval) -> None: ...

    def answer_approval(self, approval_id: str, decision: ApprovalDecision, by: str, now: datetime) -> Approval: ...

    def mark_ended(self, task_id: str, at: datetime) -> None: ...


class TaskLookup(Protocol):
    def get_task(self, task_id: str) -> TaskRecord | None: ...

    def get_approval(self, approval_id: str) -> Approval | None: ...

    def task_for_request(self, request: str) -> str | None: ...

    def chat_deleted(self, chat_id: str) -> bool: ...


class OpenWork(Protocol):
    def open_tasks(self) -> list[TaskRecord]: ...

    def pending_approvals(self, task_id: str | None = None) -> list[Approval]: ...


class ChatRecords(Protocol):
    def close_chat(self, chat_id: str) -> list[str]: ...

    def delete_chat(self, chat_id: str) -> list[str]: ...


class WorkingDataRecords(Protocol):
    """What is kept about how finished tasks were done, for the retention clean-up."""

    def ended_uncleared(self, before: datetime) -> list[str]: ...

    def clear_working_data(self, task_id: str) -> None: ...


class PromptRecords(Protocol):
    def current_prompt(self) -> tuple[int, str] | None: ...

    def save_prompt(self, text: str) -> int: ...

    def prompt_versions(self) -> list[tuple[int, str, str]]: ...


class RuleRecords(Protocol):
    def all_rules(self) -> list[AllowRule]: ...

    def rules_for_chat(self, chat_id: str) -> list[AllowRule]: ...

    def revoke_rule(self, chat_id: str, tool: str) -> bool: ...


class ManagementRecords(PromptRecords, RuleRecords, Protocol):
    """What the management API shows and changes directly."""


class SettingsRecords(Protocol):
    """Saved settings, each a JSON value under a name. Never secrets."""

    def get_setting(self, key: str) -> Any: ...

    def set_setting(self, key: str, value: Any) -> None: ...
