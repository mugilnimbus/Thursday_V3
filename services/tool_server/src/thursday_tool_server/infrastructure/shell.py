"""Shell processes: one-shot commands and persistent sessions, with process-tree kill.

PowerShell 7 (`pwsh`) is used when installed, otherwise Windows PowerShell. Output is
read incrementally into a capped buffer, so a timeout still returns what was printed.
On timeout or cancellation the whole process tree is killed (`taskkill /T`), because
killing only the parent leaves grandchildren running on Windows.
"""

import asyncio
import base64
import contextlib
import os
import pathlib
import shutil
import subprocess
import sys
import uuid

from thursday_tool_server.domain.shell_result import ShellResult

IS_WINDOWS = sys.platform == "win32"
_UTF8_PRELUDE = "$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); "


def shell_executable() -> str:
    return shutil.which("pwsh") or shutil.which("powershell") or "powershell"


class CappedBuffer:
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._parts: list[str] = []
        self._size = 0
        self.truncated = False

    def add(self, text: str) -> None:
        room = self._limit - self._size
        if room <= 0:
            self.truncated = self.truncated or bool(text)
            return
        if len(text) > room:
            text, self.truncated = text[:room], True
        self._parts.append(text)
        self._size += len(text)

    def text(self) -> str:
        return "".join(self._parts)


async def kill_tree(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    if IS_WINDOWS:
        killer = await asyncio.create_subprocess_exec(
            "taskkill",
            "/T",
            "/F",
            "/PID",
            str(process.pid),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await killer.wait()
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, 9)  # pyright: ignore[reportAttributeAccessIssue]
    with contextlib.suppress(ProcessLookupError):
        process.kill()
    await process.wait()


async def _spawn(args: list[str], cwd: pathlib.Path, stdin: int | None) -> asyncio.subprocess.Process:
    if IS_WINDOWS:
        return await asyncio.create_subprocess_exec(
            *args,
            cwd=cwd,
            stdin=stdin,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
        )
    return await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdin=stdin,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )


async def run_command(command: str, cwd: pathlib.Path, timeout: float, output_limit: int) -> ShellResult:
    args = [shell_executable(), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", _UTF8_PRELUDE + command]
    process = await _spawn(args, cwd, asyncio.subprocess.DEVNULL)
    buffer = CappedBuffer(output_limit)

    async def pump() -> None:
        assert process.stdout is not None
        while chunk := await process.stdout.read(65536):
            buffer.add(chunk.decode("utf-8", errors="replace"))

    reader = asyncio.create_task(pump())
    try:
        await asyncio.wait_for(asyncio.shield(reader), timeout=timeout)
        await process.wait()
        return ShellResult(process.returncode, buffer.text(), False, buffer.truncated)
    except TimeoutError:
        await kill_tree(process)
        reader.cancel()
        return ShellResult(None, buffer.text(), True, buffer.truncated)
    except asyncio.CancelledError:
        await kill_tree(process)
        reader.cancel()
        raise


class PersistentShell:
    """A long-lived PowerShell process; each command runs in the same session scope.

    Commands are sent base64-encoded on one line and end with a unique marker carrying
    `$LASTEXITCODE`, so multi-line commands and state (cwd, variables) work.
    """

    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self._process = process
        self._lock = asyncio.Lock()

    @classmethod
    async def start(cls, cwd: pathlib.Path) -> "PersistentShell":
        args = [shell_executable(), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", "-"]
        process = await _spawn(args, cwd, asyncio.subprocess.PIPE)
        shell = cls(process)
        await shell._send(_UTF8_PRELUDE.strip())
        return shell

    @property
    def alive(self) -> bool:
        return self._process.returncode is None

    async def run(self, command: str, timeout: float, output_limit: int) -> ShellResult:
        async with self._lock:
            marker = f"__THURSDAY_END_{uuid.uuid4().hex}__"
            encoded = base64.b64encode(command.encode("utf-8")).decode("ascii")
            line = (
                f"$global:LASTEXITCODE = 0; try {{ Invoke-Expression ([Text.Encoding]::UTF8.GetString("
                f"[Convert]::FromBase64String('{encoded}'))) 2>&1 | Out-String -Stream }} "
                f'catch {{ $_ | Out-String -Stream }}; Write-Output "{marker}$LASTEXITCODE"'
            )
            await self._send(line)
            buffer = CappedBuffer(output_limit)
            try:
                code = await asyncio.wait_for(self._read_until(marker, buffer), timeout=timeout)
            except TimeoutError:
                await self.close()
                return ShellResult(None, buffer.text(), True, buffer.truncated)
            except asyncio.CancelledError:
                await self.close()
                raise
            return ShellResult(code, buffer.text(), False, buffer.truncated)

    async def close(self) -> None:
        await kill_tree(self._process)

    async def _send(self, line: str) -> None:
        assert self._process.stdin is not None
        self._process.stdin.write((line + "\n").encode("utf-8"))
        await self._process.stdin.drain()

    async def _read_until(self, marker: str, buffer: CappedBuffer) -> int | None:
        assert self._process.stdout is not None
        while True:
            raw = await self._process.stdout.readline()
            if not raw:
                return None
            text = raw.decode("utf-8", errors="replace")
            if marker in text:
                tail = text.split(marker, 1)[1].strip()
                return int(tail) if tail.lstrip("-").isdigit() else None
            buffer.add(text)
