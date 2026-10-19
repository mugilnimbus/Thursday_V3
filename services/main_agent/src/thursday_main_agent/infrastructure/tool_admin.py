"""Asking the tool server to clean its own call logs.

The logs belong to the tool server, so this service never opens them. It runs the tool server's own one-off
commands (`forget-chat`, `forget-project`) and reads the one line of JSON each prints.
"""

import asyncio
import json
import os
import subprocess
import sys
from typing import Any

COMMAND_TIMEOUT_SECONDS = 60.0


class ToolLogCleanupFailed(Exception):
    pass


class ToolServerAdmin:
    def __init__(self, env_file: str) -> None:
        self._env_file = env_file

    async def _run(self, *arguments: str) -> dict[str, Any]:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0  # type: ignore[attr-defined]
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "thursday_tool_server",
            *arguments,
            env={**os.environ, "THURSDAY_ENV_FILE": self._env_file, "PYTHONUTF8": "1"},
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=flags,
        )
        try:
            out, _ = await asyncio.wait_for(process.communicate(), COMMAND_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            process.kill()
            raise ToolLogCleanupFailed(f"the tool server did not finish {arguments[0]} in time") from exc
        if process.returncode != 0:
            raise ToolLogCleanupFailed(f"the tool server could not run {arguments[0]} (exit {process.returncode})")
        try:
            return json.loads(out.decode("utf-8", errors="replace").strip().splitlines()[-1])
        except (ValueError, IndexError) as exc:
            raise ToolLogCleanupFailed(f"the tool server gave no answer to {arguments[0]}") from exc

    async def forget_chat(self, chat_id: str) -> int:
        """Remove a deleted chat's tool calls from every project's log. Returns how many there were."""
        return int((await self._run("forget-chat", "--chat-id", chat_id)).get("removed", 0))

    async def forget_project(self, project_id: str) -> list[str]:
        """Remove a deleted project's log. Returns the files that were there."""
        return list((await self._run("forget-project", "--project-id", project_id)).get("files", []))
