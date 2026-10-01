"""Interfaces the application layer depends on; infrastructure implements them."""

from typing import Any, Protocol

from mcp_types import CallToolResult, InputRequiredResult, Tool
from thursday_contracts.events import EventType


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
    ) -> CallToolResult | InputRequiredResult: ...
