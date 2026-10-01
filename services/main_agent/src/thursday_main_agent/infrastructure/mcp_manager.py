"""MCP client side: one built-in tool server child process per active project.

The MCP client's lifetime must stay inside one asyncio task (anyio cancel scopes), so an
owner task per project holds the connection; calls come from the task runner. A crashed
server restarts on the next call. Idle servers stop after a while, but never while a shell
session is open, because its handles would be lost.
"""

import asyncio
import contextlib
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any

from mcp.client.client import Client
from mcp.client.stdio import StdioServerParameters
from mcp_types import CallToolResult, ElicitResult, InputRequiredResult, Tool

log = logging.getLogger(__name__)
STARTUP_TIMEOUT_SECONDS = 30.0


class ToolServerUnavailable(Exception):
    pass


async def _no_auto_elicitation(context: Any, params: Any) -> ElicitResult:
    # Declares the elicitation capability. Approvals are driven by the task runner, never auto-answered.
    return ElicitResult(action="cancel")


@dataclass(slots=True)
class _ProjectServer:
    project_id: str
    folder: str
    params: StdioServerParameters
    client: Client | None = None
    tools: list[Tool] = field(default_factory=list)
    open_sessions: int = 0
    in_flight: int = 0
    last_used: float = field(default_factory=time.monotonic)
    owner: asyncio.Task[None] | None = None
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    error: BaseException | None = None

    @property
    def alive(self) -> bool:
        return self.client is not None and self.owner is not None and not self.owner.done()


class McpManager:
    def __init__(self, env_file: str, idle_stop_seconds: float) -> None:
        self._env_file = env_file
        self._idle = idle_stop_seconds
        self._servers: dict[str, _ProjectServer] = {}
        self._lock = asyncio.Lock()

    def _params(self, project_id: str, folder: str) -> StdioServerParameters:
        env = {**os.environ, "THURSDAY_ENV_FILE": self._env_file, "PYTHONUTF8": "1"}
        args = ["-m", "thursday_tool_server", "--workspace", folder, "--project-id", project_id]
        return StdioServerParameters(command=sys.executable, args=args, env=env)

    async def _own(self, server: _ProjectServer) -> None:
        try:
            async with Client(server.params, elicitation_callback=_no_auto_elicitation) as client:
                server.tools = list((await client.list_tools()).tools)
                server.client = client
                server.ready.set()
                await server.stop.wait()
        except BaseException as exc:  # recorded and surfaced to the next caller
            server.error = exc
            log.warning("tool server for project %s stopped: %s", server.project_id, type(exc).__name__)
        finally:
            server.client = None
            server.ready.set()

    async def _get(self, project_id: str, folder: str) -> _ProjectServer:
        async with self._lock:
            server = self._servers.get(project_id)
            if server is not None and server.alive and server.folder == folder:
                return server
            if server is not None:
                await self._stop(server)
            server = _ProjectServer(project_id, folder, self._params(project_id, folder))
            server.owner = asyncio.create_task(self._own(server), name=f"mcp-{project_id}")
            self._servers[project_id] = server
        try:
            await asyncio.wait_for(server.ready.wait(), STARTUP_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            raise ToolServerUnavailable("tool server did not start in time") from exc
        if server.client is None:
            raise ToolServerUnavailable(f"tool server failed to start: {type(server.error).__name__}")
        return server

    async def list_tools(self, project_id: str, folder: str) -> list[Tool]:
        return (await self._get(project_id, folder)).tools

    async def call(
        self,
        project_id: str,
        folder: str,
        name: str,
        arguments: dict[str, Any],
        *,
        input_responses: dict[str, Any] | None = None,
        request_state: str | None = None,
    ) -> CallToolResult | InputRequiredResult:
        server = await self._get(project_id, folder)
        client = server.client
        if client is None:
            raise ToolServerUnavailable("tool server is not running")
        server.in_flight += 1
        server.last_used = time.monotonic()
        try:
            result = await client.session.call_tool(
                name, arguments, input_responses=input_responses, request_state=request_state, allow_input_required=True
            )
        except Exception as exc:
            if not server.alive:
                raise ToolServerUnavailable(f"tool server crashed during {name}") from exc
            raise
        finally:
            server.in_flight -= 1
            server.last_used = time.monotonic()
        if isinstance(result, CallToolResult) and not result.is_error:
            if name == "shell.session.open":
                server.open_sessions += 1
            elif name == "shell.session.close":
                server.open_sessions = max(0, server.open_sessions - 1)
        return result  # pyright: ignore[reportReturnType]

    async def reap_idle(self) -> None:
        now = time.monotonic()
        async with self._lock:
            for project_id, server in list(self._servers.items()):
                idle = now - server.last_used >= self._idle and server.in_flight == 0 and server.open_sessions == 0
                if not server.alive or idle:
                    await self._stop(server)
                    del self._servers[project_id]

    async def stop_project(self, project_id: str) -> bool:
        """Stop one project's server now (the user asked). Its shell sessions end with it."""
        async with self._lock:
            server = self._servers.pop(project_id, None)
            if server is None:
                return False
            await self._stop(server)
            return True

    def status(self) -> dict[str, dict[str, object]]:
        return {
            p: {
                "alive": s.alive,
                "tools": len(s.tools),
                "open_sessions": s.open_sessions,
                "idle_seconds": round(time.monotonic() - s.last_used),
            }
            for p, s in self._servers.items()
        }

    @staticmethod
    async def _stop(server: _ProjectServer) -> None:
        server.stop.set()
        if server.owner is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(server.owner, timeout=10)

    async def close(self) -> None:
        async with self._lock:
            for server in self._servers.values():
                await self._stop(server)
            self._servers.clear()
