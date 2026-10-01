"""Health and readiness reports every HTTP service exposes (`GET /health`, `GET /ready`).

Health means the process is up. Readiness means it can do useful work; a service
stays up and reports not-ready when a dependency (for example the LLM endpoint) is down.
"""

from enum import StrEnum

from pydantic import BaseModel, Field

HEALTH_PATH = "/health"
READY_PATH = "/ready"


class ServiceName(StrEnum):
    GATEWAY = "gateway"
    VOICE_AGENT = "voice_agent"
    MAIN_AGENT = "main_agent"
    METRICS_COLLECTOR = "metrics_collector"
    SPEECH = "speech"


class HealthReport(BaseModel):
    service: ServiceName
    version: str
    uptime_seconds: float = Field(ge=0)


class ReadinessCheck(BaseModel):
    ok: bool
    detail: str = ""


class ReadinessReport(BaseModel):
    service: ServiceName
    ready: bool
    checks: dict[str, ReadinessCheck] = Field(default_factory=dict)
