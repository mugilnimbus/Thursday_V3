"""What the voice agent's logic needs from storage, the main agent and the gateway link, as interfaces ("ports").

Each one lists only what its user calls. `infrastructure` holds the classes that fit them, and only `bootstrap`
knows which class sits behind which port. They are structural: a class fits by having the methods.
"""

from datetime import datetime, timedelta
from typing import Any, Protocol

from thursday_contracts.events import EventType

from thursday_voice_agent.domain.tasks import DelegatedTask


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


class Outbox(Protocol):
    """This service's stored events: the ones still to send, and the sent ones kept for replay."""

    def after(self, seq: int, limit: int) -> list[dict[str, Any]]: ...

    def forget(self, *, chat_id: str | None = None, project_id: str | None = None) -> int: ...

    def prune_sent(self, older_than: timedelta) -> int: ...

    def backlog(self) -> int: ...


class MainAgent(Protocol):
    """The main agent, as the voice agent uses it. Raises `MainAgentUnavailable` when it cannot be reached and
    `MainAgentRefused` when it says no."""

    async def start_task(
        self,
        chat_id: str,
        instruction: str,
        project_id: str,
        folder: str,
        push_url: str,
        push_token: str,
        request: str | None = None,
    ) -> dict[str, Any]:
        """`request` names the request. Sent again under the same name, it gives back the task the first sending
        started instead of starting another."""
        ...

    async def get_task(self, task_id: str) -> dict[str, Any]: ...

    async def cancel(self, task_id: str) -> dict[str, Any]: ...

    async def pause(self, task_id: str) -> dict[str, Any]: ...

    async def resume(self, task_id: str) -> dict[str, Any]: ...

    async def answer(self, task_id: str, chat_id: str, approval_id: str, decision: str) -> None: ...


class ConversationRecords(Protocol):
    """A chat's transcript and its answered turns, for the conversation."""

    def transcript_count(self, chat_id: str) -> int: ...

    def transcript_from(self, chat_id: str, start: int) -> list[dict[str, Any]]: ...

    def append(self, chat_id: str, messages: list[dict[str, Any]]) -> None: ...

    def turn_reply(self, chat_id: str, client_message_id: str) -> str | None: ...

    def save_turn(self, chat_id: str, client_message_id: str, reply: str) -> None: ...

    def pending_approval(self, chat_id: str) -> DelegatedTask | None: ...

    def chat_deleted(self, chat_id: str) -> bool: ...


class TaskRecords(Protocol):
    """The tasks handed to the main agent, for the task relay."""

    def add_task(self, t: DelegatedTask) -> None: ...

    def task(self, task_id: str) -> DelegatedTask | None: ...

    def update_task(
        self,
        task_id: str,
        state: str,
        summary: str | None = None,
        approval: tuple[str, str] | None = None,
        clear_approval: bool = False,
    ) -> None: ...

    def tasks_for_chat(self, chat_id: str, open_only: bool = False) -> list[DelegatedTask]: ...

    def open_tasks(self) -> list[DelegatedTask]: ...

    def append(self, chat_id: str, messages: list[dict[str, Any]]) -> None: ...

    def chat_deleted(self, chat_id: str) -> bool: ...


class TurnRecords(Protocol):
    def prune_turns(self, before: datetime) -> int: ...


class SettingsRecords(Protocol):
    """Saved settings, each a JSON value under a name. Never secrets."""

    def get_setting(self, key: str) -> Any: ...

    def set_setting(self, key: str, value: Any) -> None: ...


class PromptRecords(Protocol):
    def current_prompt(self) -> tuple[int, str] | None: ...

    def save_prompt(self, text: str) -> int: ...

    def prompt_versions(self) -> list[tuple[int, str, str]]: ...


class ManagementRecords(PromptRecords, Protocol):
    """What the management routes show and change directly."""

    def delete_chat(self, chat_id: str) -> None: ...
