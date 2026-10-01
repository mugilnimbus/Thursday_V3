"""`GET /health` and `GET /ready` routes built from the published health contract."""

import time
from collections.abc import Awaitable, Callable, Mapping

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from thursday_contracts.health import (
    HEALTH_PATH,
    READY_PATH,
    HealthReport,
    ReadinessCheck,
    ReadinessReport,
    ServiceName,
)

ReadinessProbe = Callable[[], Awaitable[ReadinessCheck]]


def build_health_router(
    service: ServiceName, version: str, probes: Mapping[str, ReadinessProbe] | None = None
) -> APIRouter:
    """Health is always 200 while the process runs; readiness is 503 when any probe fails."""
    started = time.monotonic()
    router = APIRouter()
    registered = dict(probes or {})

    @router.get(HEALTH_PATH, response_model=HealthReport)
    async def health() -> HealthReport:
        return HealthReport(service=service, version=version, uptime_seconds=time.monotonic() - started)

    @router.get(READY_PATH, response_model=ReadinessReport)
    async def ready() -> JSONResponse:
        checks: dict[str, ReadinessCheck] = {}
        for name, probe in registered.items():
            try:
                checks[name] = await probe()
            except Exception as exc:  # a failing probe means not ready, never a crash
                checks[name] = ReadinessCheck(ok=False, detail=type(exc).__name__)
        report = ReadinessReport(service=service, ready=all(c.ok for c in checks.values()), checks=checks)
        return JSONResponse(report.model_dump(mode="json"), status_code=200 if report.ready else 503)

    return router
