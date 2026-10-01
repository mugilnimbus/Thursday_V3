"""Interfaces the supervisor depends on; infrastructure implements them."""

from typing import Protocol

from thursday_launcher.domain.supervision import ServiceSpec


class ProcessHandle(Protocol):
    @property
    def pid(self) -> int: ...

    def exit_code(self) -> int | None:
        """None while running."""
        ...

    async def stop(self, grace_seconds: float) -> None:
        """Ask the process to exit, then force it after the grace period."""
        ...


class ProcessStarter(Protocol):
    def start(self, spec: ServiceSpec) -> ProcessHandle: ...


class HealthProbe(Protocol):
    async def is_healthy(self, spec: ServiceSpec) -> bool: ...


class Clock(Protocol):
    def now(self) -> float: ...
