"""Shell use cases: one-shot commands and explicit session handles.

MCP has no session concept, so `open_session` returns a handle the model passes back.
Handles live only as long as this server process.
"""

import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from thursday_tool_server.application.files import ToolFailure
from thursday_tool_server.domain.shell_result import ShellResult
from thursday_tool_server.domain.workspace import Workspace

MAX_SESSIONS = 4


class Session(Protocol):
    @property
    def alive(self) -> bool: ...

    async def run(self, command: str, timeout: float, output_limit: int) -> ShellResult: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ShellLimits:
    default_timeout: float
    max_timeout: float
    output_limit: int

    def clamp(self, requested: float | None) -> float:
        if requested is None or requested <= 0:
            return self.default_timeout
        return min(requested, self.max_timeout)


RunCommand = Callable[..., Awaitable[ShellResult]]
StartSession = Callable[..., Awaitable[Session]]


def describe(result: ShellResult, timeout: float) -> str:
    notes = []
    if result.timed_out:
        notes.append(f"timed out after {timeout:.0f}s; the process tree was killed")
    if result.truncated:
        notes.append("output truncated")
    header = f"exit code: {result.exit_code if result.exit_code is not None else 'none'}"
    suffix = f"\n[{'; '.join(notes)}]" if notes else ""
    return f"{header}\n{result.output.rstrip()}{suffix}"


class ShellTools:
    def __init__(self, workspace: Workspace, limits: ShellLimits, run: RunCommand, start_session: StartSession) -> None:
        self._ws = workspace
        self._limits = limits
        self._run = run
        self._start_session = start_session
        self._sessions: dict[str, Session] = {}

    async def run(self, command: str, timeout_seconds: float | None = None) -> str:
        if not command.strip():
            raise ToolFailure("command is empty")
        timeout = self._limits.clamp(timeout_seconds)
        result = await self._run(command, self._ws.root, timeout, self._limits.output_limit)
        return describe(result, timeout)

    async def open_session(self) -> str:
        self._sessions = {h: s for h, s in self._sessions.items() if s.alive}
        if len(self._sessions) >= MAX_SESSIONS:
            raise ToolFailure(f"too many open sessions ({MAX_SESSIONS}); close one first")
        handle = f"sh-{secrets.token_hex(4)}"
        self._sessions[handle] = await self._start_session(self._ws.root)
        return handle

    async def exec_in_session(self, handle: str, command: str, timeout_seconds: float | None = None) -> str:
        session = self._sessions.get(handle)
        if session is None or not session.alive:
            self._sessions.pop(handle, None)
            raise ToolFailure(f"unknown or closed session: {handle}; open a new one")
        timeout = self._limits.clamp(timeout_seconds)
        result = await session.run(command, timeout, self._limits.output_limit)
        if result.timed_out:
            self._sessions.pop(handle, None)
        return describe(result, timeout) + ("\n[session closed after timeout]" if result.timed_out else "")

    async def close_session(self, handle: str) -> str:
        session = self._sessions.pop(handle, None)
        if session is None:
            return f"session {handle} was not open"
        await session.close()
        return f"closed session {handle}"

    @property
    def open_sessions(self) -> int:
        return sum(1 for s in self._sessions.values() if s.alive)

    async def close_all(self) -> None:
        for handle in list(self._sessions):
            await self.close_session(handle)
