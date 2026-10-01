import pathlib
from datetime import datetime

from thursday_contracts.health import ServiceName
from thursday_launcher.domain.supervision import ServiceSpec, ServiceState, ServiceStatus
from thursday_launcher.transport.console import Console

GW = ServiceSpec(ServiceName.GATEWAY, "thursday_gateway", 8700)
VOICE = ServiceSpec(ServiceName.VOICE_AGENT, "thursday_voice_agent", 8710)
LOGS = pathlib.Path("logs")


class Screen:
    """A console with a clock the test moves and the lines it printed."""

    def __init__(self, specs=(GW, VOICE), colour: bool = False) -> None:
        self.lines: list[str] = []
        self.t = 0.0
        self.console = Console(
            specs,
            dashboard_url="http://127.0.0.1:8700",
            proxy_port=8701,
            logs=LOGS,
            out=self.lines.append,
            colour=colour,
            clock=lambda: self.t,
            wall=lambda: datetime(2026, 10, 1, 15, 0, 58),
        )

    def change(
        self, spec: ServiceSpec, state: ServiceState, note: str = "", pid: int | None = None, restarts: int = 0
    ) -> None:
        self.console.change(
            ServiceStatus(spec=spec, state=state, pid=pid, restarts=restarts, history=[note] if note else [])
        )

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def test_start_shows_one_plain_line_per_change_and_a_summary_when_all_are_ready() -> None:
    screen = Screen()
    screen.console.header()
    screen.change(GW, ServiceState.STARTING, "started pid 111", pid=111)
    screen.change(VOICE, ServiceState.STARTING, "started pid 222", pid=222)
    screen.t = 2.0
    screen.change(GW, ServiceState.HEALTHY, "health check passed", pid=111)
    assert "All 2 services are ready" not in screen.text  # the voice agent is not ready yet
    screen.t = 3.5
    screen.change(VOICE, ServiceState.HEALTHY, "health check passed", pid=222)

    assert screen.lines[0] == "Thursday: starting 2 services"
    assert screen.lines[2] == "  15:00:58  gateway            starting        port 8700   pid 111"
    assert screen.lines[4] == "  15:00:58  gateway            ready           port 8700   after 2.0 s"
    assert screen.lines[5] == "  15:00:58  voice agent        ready           port 8710   after 3.5 s"
    assert "All 2 services are ready (3.5 s)." in screen.lines
    assert "  Dashboard   http://127.0.0.1:8700" in screen.lines
    assert any("tailscale serve --bg http://127.0.0.1:8701" in line for line in screen.lines)
    assert any(line.startswith("  Logs        logs") for line in screen.lines)
    assert any("uv run thursday down" in line for line in screen.lines)
    assert "{" not in screen.text  # no JSON on the terminal


def test_crash_says_why_where_the_log_is_and_counts_restarts() -> None:
    screen = Screen(specs=(GW,))
    screen.change(GW, ServiceState.STARTING, pid=1)
    screen.change(GW, ServiceState.HEALTHY, pid=1)
    screen.change(GW, ServiceState.CRASHED, "exited with code 1; restart in 2s")
    assert "crashed" in screen.lines[-1] and "exited with code 1; restart in 2s" in screen.lines[-1]
    assert str(LOGS / "gateway.log") in screen.lines[-1]
    screen.change(GW, ServiceState.STARTING, pid=2, restarts=1)
    assert screen.lines[-1].endswith("pid 2   restart 1")
    before = len(screen.lines)
    screen.change(GW, ServiceState.HEALTHY, pid=2)
    assert "All services are ready again." in screen.lines[before:]
    assert screen.text.count("Dashboard") == 1  # the full summary is shown once


def test_a_service_already_running_counts_as_ready() -> None:
    screen = Screen(specs=(GW,))
    screen.change(GW, ServiceState.ADOPTED, "already running on its port; adopted")
    assert "already running" in screen.lines[0] and "left as it is" in screen.lines[0]
    assert "All 1 services are ready (0.0 s)." in screen.lines


def test_slow_start_is_mentioned_once_with_the_log_file() -> None:
    screen = Screen(specs=(GW,))
    screen.change(GW, ServiceState.STARTING, pid=1)
    screen.t = 19.0
    screen.console.check_slow()
    assert len(screen.lines) == 1
    screen.t = 21.0
    screen.console.check_slow()
    screen.console.check_slow()
    assert len(screen.lines) == 2
    assert (
        "still starting" in screen.lines[1] and "21.0 s so far" in screen.lines[1] and "gateway.log" in screen.lines[1]
    )


def test_stopping_is_announced_and_stop_lines_are_short() -> None:
    screen = Screen(specs=(GW,))
    screen.change(GW, ServiceState.STARTING, pid=1)
    screen.change(GW, ServiceState.HEALTHY, pid=1)
    screen.console.stopping("Ctrl+C")
    screen.change(GW, ServiceState.STOPPED, "stopped by launcher")
    screen.console.stopped()
    assert "Stopping all services (Ctrl+C)..." in screen.lines
    assert screen.lines[-2] == "  15:00:58  gateway            stopped"
    assert screen.lines[-1] == "All services stopped."


def test_colour_is_only_added_when_asked_for() -> None:
    plain, coloured = Screen(specs=(GW,)), Screen(specs=(GW,), colour=True)
    for screen in (plain, coloured):
        screen.change(GW, ServiceState.STARTING, pid=1)
    assert "\x1b[" not in plain.text
    assert "\x1b[33m" in coloured.text  # "starting" in yellow
