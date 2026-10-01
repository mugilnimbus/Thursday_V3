from dataclasses import dataclass, field

from thursday_contracts.health import ServiceName
from thursday_launcher.application.supervisor import Supervisor
from thursday_launcher.domain.supervision import RestartPolicy, ServiceSpec, ServiceState

GW = ServiceSpec(ServiceName.GATEWAY, "thursday_gateway", 1)
MAIN = ServiceSpec(ServiceName.MAIN_AGENT, "thursday_main_agent", 2)


@dataclass
class FakeProcess:
    pid: int
    code: int | None = None
    stopped: bool = False

    def exit_code(self) -> int | None:
        return self.code

    async def stop(self, grace_seconds: float) -> None:
        self.stopped = True


@dataclass
class FakeStarter:
    started: list[FakeProcess] = field(default_factory=list)
    fail: bool = False

    def start(self, spec: ServiceSpec) -> FakeProcess:
        if self.fail:
            raise OSError("no such file")
        process = FakeProcess(pid=100 + len(self.started))
        self.started.append(process)
        return process


@dataclass
class FakeProbe:
    healthy: set[str] = field(default_factory=set)

    async def is_healthy(self, spec: ServiceSpec) -> bool:
        return spec.name in self.healthy


@dataclass
class FakeClock:
    t: float = 0.0

    def now(self) -> float:
        return self.t


def build(specs=(GW, MAIN), probe=None, starter=None):
    starter = starter or FakeStarter()
    probe = probe or FakeProbe()
    clock = FakeClock()
    policy = RestartPolicy(initial_delay=1, max_delay=8, factor=2, stable_after=60)
    return Supervisor(list(specs), starter, probe, clock, policy), starter, probe, clock


def state(sup: Supervisor, name: ServiceName) -> ServiceState:
    return next(s.state for s in sup.statuses if s.spec.name == name)


async def test_starts_every_service_and_marks_healthy() -> None:
    sup, starter, probe, _ = build()
    await sup.start_all()
    assert len(starter.started) == 2 and state(sup, ServiceName.GATEWAY) is ServiceState.STARTING
    probe.healthy = {GW.name, MAIN.name}
    await sup.tick()
    assert {s.state for s in sup.statuses} == {ServiceState.HEALTHY}


async def test_crash_restarts_after_growing_delay_without_touching_others() -> None:
    sup, starter, probe, clock = build()
    await sup.start_all()
    probe.healthy = {GW.name, MAIN.name}
    await sup.tick()
    gw_process = starter.started[0]
    for expected_delay in (1, 2, 4, 8, 8):
        gw_process.code = 1
        await sup.tick()
        assert state(sup, ServiceName.GATEWAY) is ServiceState.CRASHED
        assert state(sup, ServiceName.MAIN_AGENT) is ServiceState.HEALTHY
        clock.t += expected_delay - 0.01
        await sup.tick()
        assert state(sup, ServiceName.GATEWAY) is ServiceState.CRASHED, "restarted too early"
        clock.t += 0.01
        await sup.tick()
        assert state(sup, ServiceName.GATEWAY) is ServiceState.HEALTHY
        gw_process = starter.started[-1]
    gw = next(s for s in sup.statuses if s.spec.name == ServiceName.GATEWAY)
    assert gw.restarts == 5 and gw.last_exit_code == 1


async def test_backoff_resets_after_a_stable_run() -> None:
    sup, starter, probe, clock = build(specs=(GW,))
    await sup.start_all()
    probe.healthy = {GW.name}
    starter.started[0].code = 1
    await sup.tick()
    clock.t += 1
    await sup.tick()
    clock.t += 61
    await sup.tick()
    gw = sup.statuses[0]
    assert gw.consecutive_failures == 0


async def test_service_already_running_is_adopted_not_started_twice() -> None:
    sup, starter, probe, _ = build(specs=(GW,), probe=FakeProbe(healthy={GW.name}))
    await sup.start_all()
    assert starter.started == [] and state(sup, ServiceName.GATEWAY) is ServiceState.ADOPTED
    probe.healthy.clear()
    await sup.tick()
    assert len(starter.started) == 1 and state(sup, ServiceName.GATEWAY) is ServiceState.STARTING


async def test_start_failure_is_a_crash_with_a_retry() -> None:
    sup, starter, _, clock = build(specs=(GW,), starter=FakeStarter(fail=True))
    await sup.start_all()
    assert state(sup, ServiceName.GATEWAY) is ServiceState.CRASHED
    starter.fail = False
    clock.t += 1
    await sup.tick()
    assert state(sup, ServiceName.GATEWAY) is ServiceState.STARTING


async def test_stop_all_stops_every_running_process() -> None:
    sup, starter, _, _ = build()
    await sup.start_all()
    await sup.stop_all()
    assert all(p.stopped for p in starter.started)
    assert {s.state for s in sup.statuses} == {ServiceState.STOPPED}
