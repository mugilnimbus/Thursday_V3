"""Supervision loop: start services, watch health, restart crashes with a delay.

Each service is independent: one crashing or unhealthy service never stops the others.
A service already answering on its port (for example started by hand) is adopted, not
started twice.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable, Sequence

from thursday_launcher.application.ports import Clock, HealthProbe, ProcessHandle, ProcessStarter
from thursday_launcher.domain.supervision import RestartPolicy, ServiceSpec, ServiceState, ServiceStatus

log = logging.getLogger(__name__)
HISTORY_LIMIT = 20


class Supervisor:
    def __init__(
        self,
        specs: Sequence[ServiceSpec],
        starter: ProcessStarter,
        probe: HealthProbe,
        clock: Clock,
        policy: RestartPolicy | None = None,
        on_change: Callable[[ServiceStatus], None] | None = None,
    ) -> None:
        self._starter = starter
        self._probe = probe
        self._clock = clock
        self._policy = policy or RestartPolicy()
        self._on_change = on_change
        self._statuses = {spec.name: ServiceStatus(spec=spec) for spec in specs}
        self._handles: dict[str, ProcessHandle] = {}

    @property
    def statuses(self) -> list[ServiceStatus]:
        return list(self._statuses.values())

    async def start_all(self) -> None:
        results = await asyncio.gather(*(self._probe.is_healthy(s.spec) for s in self._statuses.values()))
        for status, already_up in zip(self._statuses.values(), results, strict=True):
            if already_up:
                self._set(status, ServiceState.ADOPTED, "already running on its port; adopted")
            else:
                self._spawn(status)

    async def tick(self) -> None:
        """One supervision pass. Called on a fixed interval by `run`."""
        now = self._clock.now()
        for status in self._statuses.values():
            self._reap_if_exited(status, now)
            if status.state is ServiceState.CRASHED and status.restart_at is not None and now >= status.restart_at:
                status.restarts += 1
                self._spawn(status)
        watched = [
            s
            for s in self._statuses.values()
            if s.state in (ServiceState.STARTING, ServiceState.HEALTHY, ServiceState.UNHEALTHY, ServiceState.ADOPTED)
        ]
        results = await asyncio.gather(*(self._probe.is_healthy(s.spec) for s in watched))
        for status, healthy in zip(watched, results, strict=True):
            self._apply_probe(status, healthy, now)

    async def run(self, stop: asyncio.Event, interval: float = 1.0) -> None:
        await self.start_all()
        while not stop.is_set():
            await self.tick()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=interval)
        await self.stop_all()

    async def stop_all(self, grace_seconds: float = 10.0) -> None:
        handles = list(self._handles.items())
        await asyncio.gather(*(handle.stop(grace_seconds) for _, handle in handles))
        for name, _ in handles:
            status = self._statuses[name]  # pyright: ignore[reportArgumentType]
            status.pid = None
            self._set(status, ServiceState.STOPPED, "stopped by launcher")
        self._handles.clear()

    def _spawn(self, status: ServiceStatus) -> None:
        try:
            handle = self._starter.start(status.spec)
        except OSError as exc:
            self._crashed(status, None, self._clock.now(), f"could not start: {exc}")
            return
        self._handles[status.spec.name] = handle
        status.pid = handle.pid
        status.started_at = self._clock.now()
        status.restart_at = None
        self._set(status, ServiceState.STARTING, f"started pid {handle.pid}")

    def _reap_if_exited(self, status: ServiceStatus, now: float) -> None:
        handle = self._handles.get(status.spec.name)
        if handle is None:
            return
        code = handle.exit_code()
        if code is None:
            return
        del self._handles[status.spec.name]
        self._crashed(status, code, now, f"exited with code {code}")

    def _crashed(self, status: ServiceStatus, code: int | None, now: float, reason: str) -> None:
        status.pid = None
        status.last_exit_code = code
        status.consecutive_failures += 1
        delay = self._policy.delay_for(status.consecutive_failures)
        status.restart_at = now + delay
        self._set(status, ServiceState.CRASHED, f"{reason}; restart in {delay:.0f}s")

    def _apply_probe(self, status: ServiceStatus, healthy: bool, now: float) -> None:
        if status.state is ServiceState.ADOPTED:
            if not healthy:
                self._set(status, ServiceState.STOPPED, "adopted service stopped answering; starting our own")
                self._spawn(status)
            return
        if healthy:
            if status.started_at is not None and now - status.started_at >= self._policy.stable_after:
                status.consecutive_failures = 0
            if status.state is not ServiceState.HEALTHY:
                self._set(status, ServiceState.HEALTHY, "health check passed")
        elif status.state is ServiceState.HEALTHY:
            self._set(status, ServiceState.UNHEALTHY, "health check failed")

    def _set(self, status: ServiceStatus, state: ServiceState, note: str) -> None:
        status.state = state
        status.history.append(note)
        del status.history[:-HISTORY_LIMIT]
        log.info("%s: %s (%s)", status.spec.name, state, note)
        if self._on_change is not None:
            self._on_change(status)
