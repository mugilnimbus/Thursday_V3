"""What `thursday up` shows in the terminal.

One short line per change, in plain words, with the time, the service, its state, and the detail that matters
for that state (port and pid when it starts, how long it took when it is ready, the reason and the log file
when it crashes). When every service is ready it prints where the dashboard is, how the phone connects,
where the logs are, and how to stop. The full structured log still goes to the launcher's log file.
"""

import os
import pathlib
import sys
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import TextIO

from thursday_launcher.domain.supervision import ServiceSpec, ServiceState, ServiceStatus

SLOW_START_SECONDS = 20.0
NAME_WIDTH = 18
STATE_WIDTH = 15

GREEN, YELLOW, RED, DIM, BOLD = "32", "33", "31", "2", "1"

# The word shown for each state, and its colour.
WORDS: dict[ServiceState, tuple[str, str]] = {
    ServiceState.STARTING: ("starting", YELLOW),
    ServiceState.HEALTHY: ("ready", GREEN),
    ServiceState.ADOPTED: ("already running", GREEN),
    ServiceState.UNHEALTHY: ("not answering", YELLOW),
    ServiceState.CRASHED: ("crashed", RED),
    ServiceState.STOPPED: ("stopped", DIM),
}
READY = (ServiceState.HEALTHY, ServiceState.ADOPTED)


def display_name(spec: ServiceSpec) -> str:
    return str(spec.name).replace("_", " ")


def colour_supported(stream: TextIO) -> bool:
    """True when the stream is a terminal that shows colours (on Windows, after turning that on)."""
    if os.environ.get("NO_COLOR") or not stream.isatty():
        return False
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # standard output
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except (AttributeError, OSError):
        return False


def seconds(value: float) -> str:
    return f"{value:.1f} s" if value < 60 else f"{value / 60:.1f} min"


class Console:
    def __init__(
        self,
        specs: Sequence[ServiceSpec],
        *,
        dashboard_url: str,
        proxy_port: int,
        logs: pathlib.Path,
        out: Callable[[str], None] | None = None,
        colour: bool = False,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._specs = list(specs)
        self._dashboard_url = dashboard_url
        self._proxy_port = proxy_port
        self._logs = logs
        self._out = out or (lambda line: print(line, flush=True))
        self._colour = colour
        self._clock = clock
        self._wall = wall
        self._began = clock()
        self._states: dict[str, ServiceState] = {}
        self._started: dict[str, float] = {}
        self._slow: set[str] = set()
        self._announced = False
        self._all_ready = False
        self._stopping = False

    # ---- lines ----

    def _paint(self, text: str, code: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if self._colour else text

    def _line(self, spec: ServiceSpec, word: str, code: str, detail: str) -> None:
        stamp = self._paint(self._wall().strftime("%H:%M:%S"), DIM)
        state = self._paint(f"{word:<{STATE_WIDTH}}", code)
        self._out(f"  {stamp}  {display_name(spec):<{NAME_WIDTH}} {state} {detail}".rstrip())

    def _log_file(self, spec: ServiceSpec) -> pathlib.Path:
        return self._logs / f"{spec.name}.log"

    def header(self) -> None:
        self._out(self._paint(f"Thursday: starting {len(self._specs)} services", BOLD))
        self._out("")

    def change(self, status: ServiceStatus) -> None:
        """Called by the supervisor every time a service changes state."""
        spec = status.spec
        name = str(spec.name)
        state = status.state
        now = self._clock()
        self._states[name] = state
        word, code = WORDS[state]
        detail = ""
        if state is ServiceState.STARTING:
            self._started[name] = now
            self._slow.discard(name)
            detail = f"port {spec.port:<6} pid {status.pid}"
            if status.restarts:
                detail += f"   restart {status.restarts}"
        elif state is ServiceState.HEALTHY:
            took = now - self._started.pop(name, now)
            detail = f"port {spec.port:<6} after {seconds(took)}"
        elif state is ServiceState.ADOPTED:
            detail = f"port {spec.port:<6} started elsewhere; left as it is"
        elif state is ServiceState.UNHEALTHY:
            detail = f"its health check failed; watching   log: {self._log_file(spec)}"
        elif state is ServiceState.CRASHED:
            reason = status.history[-1] if status.history else "stopped unexpectedly"
            detail = f"{reason}   log: {self._log_file(spec)}"
        elif self._stopping:
            detail = ""
        elif status.history:
            detail = status.history[-1]
        self._line(spec, word, code, detail)
        self._summarise()

    def _summarise(self) -> None:
        ready = len(self._specs) > 0 and all(self._states.get(str(s.name)) in READY for s in self._specs)
        if ready and not self._all_ready and not self._stopping:
            if self._announced:
                self._out("")
                self._out(self._paint("All services are ready again.", GREEN))
                self._out("")
            else:
                self._announced = True
                self._ready_block()
        self._all_ready = ready

    def _ready_block(self) -> None:
        took = seconds(self._clock() - self._began)
        self._out("")
        self._out(self._paint(f"All {len(self._specs)} services are ready ({took}).", GREEN))
        self._out("")
        self._out(f"  Dashboard   {self._dashboard_url}")
        self._out(
            f"  Phone       pair in Settings, Devices (needs: tailscale serve --bg http://127.0.0.1:{self._proxy_port})"
        )
        self._out(f"  Logs        {self._logs}")
        self._out("  Stop        Ctrl+C here, or `uv run thursday down` from any terminal")
        self._out("")

    def check_slow(self) -> None:
        """Say so once when a service has been starting for a long time. Call it every second or so."""
        now = self._clock()
        for spec in self._specs:
            name = str(spec.name)
            begun = self._started.get(name)
            if (
                self._states.get(name) is ServiceState.STARTING
                and begun is not None
                and name not in self._slow
                and now - begun >= SLOW_START_SECONDS
            ):
                self._slow.add(name)
                self._line(
                    spec, "still starting", YELLOW, f"{seconds(now - begun)} so far   log: {self._log_file(spec)}"
                )

    def stopping(self, why: str) -> None:
        self._stopping = True
        self._out("")
        self._out(self._paint(f"Stopping all services ({why})...", BOLD))

    def stopped(self) -> None:
        self._out(self._paint("All services stopped.", BOLD))
