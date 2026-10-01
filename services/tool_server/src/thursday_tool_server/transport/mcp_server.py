"""MCP stdio transport: tool registration, the permission gate, and auditing.

Tools whose policy is ASK take an approval parameter filled by a resolver. On protocol
2026-07-28 the SDK turns it into an input-required result with a yes/no form and
resumes when the client retries with the answer. Accept runs the tool; decline and
cancel (no answer in time) do not, and the model is told which.
"""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Annotated, Any

from mcp.server.elicitation import AcceptedElicitation, CancelledElicitation, ElicitationResult
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.resolve import Elicit, Resolve
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field

from thursday_tool_server.application.audit import CallAudit
from thursday_tool_server.application.files import FileTools, ToolFailure
from thursday_tool_server.application.shell_tools import ShellTools
from thursday_tool_server.domain.policy import Decision, ToolName, decision_for
from thursday_tool_server.domain.workspace import SandboxViolation

INSTRUCTIONS = (
    "Files and shell inside one project folder. Paths are relative to the project folder; anything outside is "
    "refused. Shell commands and deletes ask the user first; if the user declines or does not answer, the action "
    "did not happen."
)
SUMMARY_LIMIT = 500


class Approve(BaseModel):
    approve: bool = Field(default=True, description="Allow this action")


def _short(text: str) -> str:
    return text if len(text) <= SUMMARY_LIMIT else text[:SUMMARY_LIMIT] + "..."


def ask_shell(command: str) -> Elicit[Approve]:
    return Elicit(f"Run shell command: {_short(command)}", Approve)


def ask_session_exec(handle: str, command: str) -> Elicit[Approve]:
    return Elicit(f"Run in shell session {handle}: {_short(command)}", Approve)


def ask_delete(path: str, recursive: bool = False) -> Elicit[Approve]:
    what = "folder and everything in it" if recursive else "file or empty folder"
    return Elicit(f"Delete {what}: {_short(path)}", Approve)


ApprovalParam = ElicitationResult[Approve]


class ToolServer:
    def __init__(
        self,
        files: FileTools,
        shell: ShellTools,
        audit: CallAudit,
        version: str,
        lifespan: Callable[[Any], AbstractAsyncContextManager[None]] | None = None,
    ) -> None:
        self._files = files
        self._shell = shell
        self._audit = audit
        self.mcp = MCPServer("thursday-tools", instructions=INSTRUCTIONS, version=version, lifespan=lifespan)
        self._register()

    async def _audited(
        self, tool: ToolName, arguments: dict[str, Any], permission: str, action: Callable[[], Awaitable[str]]
    ) -> str:
        record = self._audit.start(tool.value, arguments, permission)
        try:
            result = await action()
        except (ToolFailure, SandboxViolation) as exc:
            self._audit.finish(record, "error", str(exc))
            raise ToolError(str(exc)) from exc
        except asyncio.CancelledError:
            self._audit.finish(record, "cancelled")
            raise
        except Exception as exc:
            self._audit.finish(record, "error", type(exc).__name__)
            raise ToolError(f"internal error in {tool.value}: {type(exc).__name__}") from exc
        self._audit.finish(record, "ok")
        return result

    async def _gated(
        self, tool: ToolName, arguments: dict[str, Any], approval: ApprovalParam, action: Callable[[], Awaitable[str]]
    ) -> str:
        assert decision_for(tool) is Decision.ASK
        if isinstance(approval, AcceptedElicitation) and approval.data.approve:
            return await self._audited(tool, arguments, "ask:accepted", action)
        if isinstance(approval, CancelledElicitation):
            self._audit.finish(self._audit.start(tool.value, arguments, "ask:no_response"), "not_run")
            return "Not run: the user did not respond in time. Try another approach or ask the user."
        self._audit.finish(self._audit.start(tool.value, arguments, "ask:declined"), "not_run")
        return "Not run: the user denied this action. Do not retry it; choose another approach or ask the user."

    def _register(self) -> None:
        files, shell, mcp = self._files, self._shell, self.mcp
        read_only = ToolAnnotations(read_only_hint=True, destructive_hint=False)
        writes = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True)
        destructive = ToolAnnotations(read_only_hint=False, destructive_hint=True)

        @mcp.tool(
            name=ToolName.FS_READ,
            annotations=read_only,
            description="Read a text file with line numbers. offset is the first line (1-based).",
        )
        async def fs_read(path: str, offset: int = 1, limit: int = 2000) -> str:
            return await self._audited(
                ToolName.FS_READ,
                {"path": path, "offset": offset, "limit": limit},
                "allow",
                lambda: asyncio.to_thread(files.read, path, offset, limit),
            )

        @mcp.tool(name=ToolName.FS_LIST, annotations=read_only, description="List a folder (folders end with /).")
        async def fs_list(path: str = ".") -> str:
            return await self._audited(
                ToolName.FS_LIST, {"path": path}, "allow", lambda: asyncio.to_thread(files.list, path)
            )

        @mcp.tool(
            name=ToolName.FS_WRITE,
            annotations=writes,
            description="Create or overwrite a text file with the given content (UTF-8).",
        )
        async def fs_write(path: str, content: str) -> str:
            return await self._audited(
                ToolName.FS_WRITE,
                {"path": path, "chars": len(content)},
                "allow",
                lambda: asyncio.to_thread(files.write, path, content),
            )

        @mcp.tool(
            name=ToolName.FS_EDIT,
            annotations=writes,
            description="Replace old_string with new_string in a file. old_string must match exactly and be "
            "unique unless replace_all is true.",
        )
        async def fs_edit(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
            return await self._audited(
                ToolName.FS_EDIT,
                {"path": path, "replace_all": replace_all},
                "allow",
                lambda: asyncio.to_thread(files.edit, path, old_string, new_string, replace_all),
            )

        @mcp.tool(
            name=ToolName.FS_PATCH,
            annotations=writes,
            description="Apply a unified diff (with @@ hunk headers) to one file.",
        )
        async def fs_patch(path: str, diff: str) -> str:
            return await self._audited(
                ToolName.FS_PATCH,
                {"path": path, "diff_chars": len(diff)},
                "allow",
                lambda: asyncio.to_thread(files.patch, path, diff),
            )

        @mcp.tool(
            name=ToolName.FS_DELETE,
            annotations=destructive,
            description="Delete a file, an empty folder, or (recursive=true) a folder and its contents. "
            "Asks the user first.",
        )
        async def fs_delete(
            path: str, approval: Annotated[ApprovalParam, Resolve(ask_delete)], recursive: bool = False
        ) -> str:
            return await self._gated(
                ToolName.FS_DELETE,
                {"path": path, "recursive": recursive},
                approval,
                lambda: asyncio.to_thread(files.delete, path, recursive),
            )

        @mcp.tool(
            name=ToolName.SHELL,
            annotations=destructive,
            description="Run a PowerShell command in the project folder and return its output. Asks the user "
            "first. timeout_seconds is capped by the server.",
        )
        async def run_shell(
            command: str, approval: Annotated[ApprovalParam, Resolve(ask_shell)], timeout_seconds: float | None = None
        ) -> str:
            return await self._gated(
                ToolName.SHELL,
                {"command": command, "timeout_seconds": timeout_seconds},
                approval,
                lambda: shell.run(command, timeout_seconds),
            )

        @mcp.tool(
            name=ToolName.SHELL_SESSION_OPEN,
            annotations=writes,
            description="Open a persistent PowerShell session (keeps folder and variables between commands). "
            "Returns a handle for shell.session.exec.",
        )
        async def session_open() -> str:
            return await self._audited(ToolName.SHELL_SESSION_OPEN, {}, "allow", shell.open_session)

        @mcp.tool(
            name=ToolName.SHELL_SESSION_EXEC,
            annotations=destructive,
            description="Run a command in an open shell session. Asks the user first.",
        )
        async def session_exec(
            handle: str,
            command: str,
            approval: Annotated[ApprovalParam, Resolve(ask_session_exec)],
            timeout_seconds: float | None = None,
        ) -> str:
            return await self._gated(
                ToolName.SHELL_SESSION_EXEC,
                {"handle": handle, "command": command},
                approval,
                lambda: shell.exec_in_session(handle, command, timeout_seconds),
            )

        @mcp.tool(name=ToolName.SHELL_SESSION_CLOSE, annotations=writes, description="Close a shell session.")
        async def session_close(handle: str) -> str:
            return await self._audited(
                ToolName.SHELL_SESSION_CLOSE, {"handle": handle}, "allow", lambda: shell.close_session(handle)
            )
