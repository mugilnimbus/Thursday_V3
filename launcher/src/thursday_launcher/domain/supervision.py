"""What the launcher supervises and the rules for restarting it."""

from dataclasses import dataclass, field
from enum import StrEnum

from thursday_contracts.health import ServiceName


@dataclass(frozen=True, slots=True)
class ServiceSpec:
    name: ServiceName
    module: str
    port: int


@dataclass(frozen=True, slots=True)
class RestartPolicy:
    """Exponential delay between restarts, capped; the delay resets after a stable run."""

    initial_delay: float = 1.0
    max_delay: float = 30.0
    factor: float = 2.0
    stable_after: float = 60.0

    def delay_for(self, consecutive_failures: int) -> float:
        if consecutive_failures <= 0:
            return 0.0
        return min(self.max_delay, self.initial_delay * self.factor ** (consecutive_failures - 1))


class ServiceState(StrEnum):
    STARTING = "starting"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    CRASHED = "crashed"
    ADOPTED = "adopted"
    STOPPED = "stopped"


@dataclass(slots=True)
class ServiceStatus:
    """Mutable runtime status of one supervised service."""

    spec: ServiceSpec
    state: ServiceState = ServiceState.STOPPED
    pid: int | None = None
    restarts: int = 0
    consecutive_failures: int = 0
    last_exit_code: int | None = None
    started_at: float | None = None
    restart_at: float | None = None
    history: list[str] = field(default_factory=list)
