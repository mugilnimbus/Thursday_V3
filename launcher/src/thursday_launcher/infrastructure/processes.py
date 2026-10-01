"""Native child processes for services (`python -m <module>`), with graceful stop."""

import asyncio
import contextlib
import os
import pathlib
import signal
import subprocess
import sys
import time
from typing import IO

import httpx
from thursday_contracts.health import HEALTH_PATH
from thursday_runtime.serve import LOCALHOST

from thursday_launcher.domain.supervision import ServiceSpec

IS_WINDOWS = sys.platform == "win32"


class ChildProcess:
    def __init__(self, popen: subprocess.Popen[bytes], output: IO[bytes]) -> None:
        self._popen = popen
        self._output = output

    @property
    def pid(self) -> int:
        return self._popen.pid

    def exit_code(self) -> int | None:
        code = self._popen.poll()
        if code is not None:
            self._output.close()
        return code

    async def stop(self, grace_seconds: float) -> None:
        if self._popen.poll() is None:
            with contextlib.suppress(OSError):
                if IS_WINDOWS:
                    # Needs CREATE_NEW_PROCESS_GROUP; uvicorn shuts down cleanly on it.
                    os.kill(self._popen.pid, signal.CTRL_BREAK_EVENT)
                else:
                    self._popen.terminate()
            deadline = time.monotonic() + grace_seconds
            while self._popen.poll() is None and time.monotonic() < deadline:  # noqa: ASYNC110 - Popen has no awaitable exit
                await asyncio.sleep(0.1)
            if self._popen.poll() is None:
                self._popen.kill()
                await asyncio.to_thread(self._popen.wait)
        self._output.close()


class SubprocessStarter:
    """Starts each service with the launcher's own interpreter, from the repository root."""

    def __init__(self, workdir: pathlib.Path, output_dir: pathlib.Path) -> None:
        self._workdir = workdir
        self._output_dir = output_dir

    def start(self, spec: ServiceSpec) -> ChildProcess:
        # Captures anything printed before the service's own logging is configured (for example import errors).
        output = open(self._output_dir / f"{spec.name}.stdout.log", "ab")  # noqa: SIM115 - closed by ChildProcess
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0
        try:
            popen = subprocess.Popen(  # noqa: S603 - fixed interpreter and module name
                [sys.executable, "-m", spec.module],
                cwd=self._workdir,
                stdout=output,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=flags,
            )
        except OSError:
            output.close()
            raise
        return ChildProcess(popen, output)


class HttpHealthProbe:
    def __init__(self, timeout: float = 2.0) -> None:
        self._client = httpx.AsyncClient(timeout=timeout)

    async def is_healthy(self, spec: ServiceSpec) -> bool:
        try:
            response = await self._client.get(f"http://{LOCALHOST}:{spec.port}{HEALTH_PATH}")
        except httpx.HTTPError:
            return False
        return response.status_code == 200 and response.json().get("service") == spec.name

    async def aclose(self) -> None:
        await self._client.aclose()


class PsutilPortKiller:
    """Stops whatever listens on a localhost port, with its child processes (the tool servers, for example)."""

    def kill(self, port: int) -> bool:
        import psutil

        found = False
        for conn in psutil.net_connections(kind="tcp"):
            if conn.status != psutil.CONN_LISTEN or not conn.laddr or conn.laddr.port != port or not conn.pid:
                continue
            with contextlib.suppress(psutil.Error):
                process = psutil.Process(conn.pid)
                family = [*process.children(recursive=True), process]
                for p in family:
                    with contextlib.suppress(psutil.Error):
                        p.kill()
                psutil.wait_procs(family, timeout=5)
                found = True
        return found

    def kill_pid(self, pid: int) -> bool:
        import psutil

        try:
            process = psutil.Process(pid)
            if "python" not in process.name().lower() and "thursday" not in process.name().lower():
                return False  # the recorded number now belongs to some other program
            family = [*process.children(recursive=True), process]
        except psutil.Error:
            return False
        for p in family:
            with contextlib.suppress(psutil.Error):
                p.kill()
        psutil.wait_procs(family, timeout=5)
        return True


class MonotonicClock:
    def now(self) -> float:
        return time.monotonic()
