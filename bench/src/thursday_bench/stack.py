"""An isolated copy of the Thursday stack for a benchmark run.

It has its own data folder, its own ports (187xx), its own service token and its own env file, and its agents call the
fake model. It never touches a stack that is already running: `refuse_if_running` stops the run first.
"""

import contextlib
import os
import pathlib
import secrets
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field

import httpx
import psutil

PORTS = {
    "GATEWAY_LOCALHOST_PORT": 18700,
    "GATEWAY_PROXY_PORT": 18701,
    "VOICE_AGENT_PORT": 18710,
    "MAIN_AGENT_PORT": 18711,
    "METRICS_COLLECTOR_PORT": 18720,
    "SPEECH_PORT": 18730,
}
FAKE_MODEL_PORT = 18790
GATEWAY = f"http://127.0.0.1:{PORTS['GATEWAY_LOCALHOST_PORT']}"
SERVICE_MODULES = (
    "thursday_gateway",
    "thursday_voice_agent",
    "thursday_main_agent",
    "thursday_metrics_collector",
    "thursday_speech",
    "thursday_tool_server",
)
OWNER_PORTS = (8700, 8701, 8710, 8711, 8720, 8730)


class StackError(Exception):
    pass


def _is_launcher(arguments: list[str]) -> bool:
    """A Python process started as `-m thursday_launcher ...` or as the `thursday` command with `up`."""
    if not arguments or not pathlib.Path(arguments[0]).name.startswith("python"):
        return False
    rest = arguments[1:]
    if rest[:2] == ["-m", "thursday_launcher"]:
        return True
    return bool(rest) and pathlib.Path(rest[0]).name == "thursday" and "up" in rest[1:]


def refuse_if_running() -> None:
    """Stop before anything starts if another Thursday stack, or something on our ports, is running."""
    for process in psutil.process_iter(["pid", "cmdline"]):
        if _is_launcher(process.info["cmdline"] or []):
            raise StackError(f"A Thursday stack is already running (pid {process.info['pid']}). Stop it first.")
    for port in (*OWNER_PORTS, *PORTS.values(), FAKE_MODEL_PORT):
        with socket.socket() as probe:
            probe.settimeout(0.2)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise StackError(f"Port {port} is in use. Stop what uses it, then run again.")


@dataclass
class Stack:
    root: pathlib.Path
    token: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    launcher: subprocess.Popen[bytes] | None = None
    fake: subprocess.Popen[bytes] | None = None

    @property
    def data_dir(self) -> pathlib.Path:
        return self.root / "data"

    @property
    def project_dir(self) -> pathlib.Path:
        return self.root / "project"

    def _env_file(self) -> pathlib.Path:
        fake_url = f"http://127.0.0.1:{FAKE_MODEL_PORT}"
        lines = [f"THURSDAY_DATA_DIR={self.data_dir}", f"THURSDAY_SERVICE_TOKEN={self.token}"]
        lines += [f"{name}={port}" for name, port in PORTS.items()]
        for agent in ("VOICE", "MAIN"):
            lines += [f"{agent}_LLM_PROVIDER=openai_compatible", f"{agent}_LLM_BASE_URL={fake_url}"]
            lines += [f"{agent}_LLM_MODEL=bench-fake"]
        lines += ["LOG_LEVEL=WARNING", "BACKUP_DAILY=false"]
        path = self.root / "bench.env"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        path.chmod(0o600)
        return path

    def start(self) -> None:
        refuse_if_running()
        self.root.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(exist_ok=True)
        self.project_dir.mkdir(exist_ok=True)
        env = {**os.environ, "THURSDAY_ENV_FILE": str(self._env_file()), "THURSDAY_DATA_DIR": str(self.data_dir)}
        env.update({name: str(port) for name, port in PORTS.items()})
        logs = self.root / "logs"
        logs.mkdir(exist_ok=True)
        self.fake = subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "thursday_bench", "fake-model", "--port", str(FAKE_MODEL_PORT)],
            env=env,
            stdout=(logs / "fake_model.log").open("wb"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.launcher = subprocess.Popen(
            [sys.executable, "-m", "thursday_launcher", "up"],
            env=env,
            stdout=(logs / "launcher.log").open("wb"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self._wait_ready()

    def _wait_ready(self, seconds: float = 90.0) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.launcher is not None and self.launcher.poll() is not None:
                raise StackError(f"The launcher stopped (exit {self.launcher.returncode}). See {self.root}/logs.")
            try:
                if all(
                    httpx.get(f"http://127.0.0.1:{port}/health", timeout=1).status_code == 200
                    for port in (
                        PORTS["GATEWAY_LOCALHOST_PORT"],
                        PORTS["VOICE_AGENT_PORT"],
                        PORTS["MAIN_AGENT_PORT"],
                    )
                ):
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        raise StackError(f"The stack was not ready after {seconds:.0f} s. See {self.root}/logs.")

    def service_processes(self) -> dict[str, list[psutil.Process]]:
        """Our launcher's child processes, grouped by service module."""
        found: dict[str, list[psutil.Process]] = {}
        if self.launcher is None:
            return found
        try:
            children = psutil.Process(self.launcher.pid).children(recursive=True)
        except psutil.NoSuchProcess:
            return found
        for child in children:
            try:
                line = " ".join(child.cmdline())
            except psutil.Error:
                continue
            for module in SERVICE_MODULES:
                if module in line:
                    found.setdefault(module, []).append(child)
        return found

    def stop(self) -> None:
        for process in (self.launcher, self.fake):
            if process is None or process.poll() is not None:
                continue
            _end_tree(process.pid, force=False)
        for process in (self.launcher, self.fake):
            if process is None:
                continue
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                _end_tree(process.pid, force=True)
                process.wait(timeout=10)


def _end_tree(pid: int, *, force: bool) -> None:
    """Stop a process and everything it started: its process group on Linux, its process tree on Windows."""
    if sys.platform == "win32":
        try:
            root = psutil.Process(pid)
            tree = [*root.children(recursive=True), root]
        except psutil.NoSuchProcess:
            return
        for process in tree:
            with contextlib.suppress(psutil.Error):
                process.kill() if force else process.terminate()
    else:
        os.killpg(pid, signal.SIGKILL if force else signal.SIGTERM)
