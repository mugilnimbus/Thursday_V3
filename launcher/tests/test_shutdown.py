from pathlib import Path

from thursday_contracts.health import ServiceName
from thursday_launcher.application.shutdown import STOP_FILE, shut_down
from thursday_launcher.domain.supervision import ServiceSpec

SPECS = [ServiceSpec(ServiceName.GATEWAY, "g", 1), ServiceSpec(ServiceName.SPEECH, "s", 2)]


class Fleet:
    """Services that stop when the supervisor sees the request file, except the orphans."""

    def __init__(self, root: Path, up: set[int], orphans: set[int] = frozenset()) -> None:  # type: ignore[assignment]
        self.root, self.up, self.orphans, self.killed = root, set(up), set(orphans), []

    async def is_healthy(self, spec: ServiceSpec) -> bool:
        if (self.root / STOP_FILE).exists():
            self.up &= self.orphans
        return spec.port in self.up

    def kill_pid(self, pid: int) -> bool:
        self.killed.append(-pid)
        return True

    def kill(self, port: int) -> bool:
        self.killed.append(port)
        self.up.discard(port)
        return True


async def test_nothing_running_is_reported_and_no_request_is_left(tmp_path: Path) -> None:
    fleet = Fleet(tmp_path, set())
    assert set((await shut_down(SPECS, tmp_path, fleet, fleet)).values()) == {"was not running"}
    assert not (tmp_path / STOP_FILE).exists()


async def test_supervisor_stops_services_cleanly(tmp_path: Path) -> None:
    fleet = Fleet(tmp_path, {1, 2})
    outcome = await shut_down(SPECS, tmp_path, fleet, fleet, interval=0.01)
    assert outcome == {"gateway": "stopped", "speech": "stopped"} and fleet.killed == []
    assert not (tmp_path / STOP_FILE).exists(), "the request is removed so the next `up` is not stopped"


async def test_a_service_left_behind_is_force_stopped(tmp_path: Path) -> None:
    fleet = Fleet(tmp_path, {1, 2}, orphans={2})
    outcome = await shut_down(SPECS, tmp_path, fleet, fleet, wait_seconds=0.05, interval=0.01)
    assert outcome == {"gateway": "stopped", "speech": "force stopped"} and fleet.killed == [2]


async def test_a_supervisor_that_does_not_react_is_stopped_before_its_services(tmp_path: Path) -> None:
    (tmp_path / "launcher.pid").write_text("4242", encoding="utf-8")
    fleet = Fleet(tmp_path, {1, 2}, orphans={1, 2})
    outcome = await shut_down(SPECS, tmp_path, fleet, fleet, wait_seconds=0.05, interval=0.01)
    assert fleet.killed == [-4242, 1, 2], "supervisor first, so it cannot restart them"
    assert set(outcome.values()) == {"force stopped"} and not (tmp_path / "launcher.pid").exists()
