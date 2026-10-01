"""Composition root: settings, the sampling loop, and health."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI
from pydantic import Field
from pydantic_settings import SettingsConfigDict
from thursday_contracts.health import ServiceName
from thursday_runtime.health import build_health_router
from thursday_runtime.log_setup import configure_logging
from thursday_runtime.paths import log_dir
from thursday_runtime.serve import LOCALHOST, serve
from thursday_runtime.settings import CommonSettings, env_file

from thursday_metrics_collector import __version__
from thursday_metrics_collector.application.collector import Collector, Host, Target

SERVICE = ServiceName.METRICS_COLLECTOR


class CollectorSettings(CommonSettings):
    model_config = SettingsConfigDict(
        env_file=env_file(), env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )

    metrics_sample_interval_seconds: float = Field(default=1, ge=1, le=300)


def create_app(settings: CollectorSettings | None = None, host: Host | None = None) -> FastAPI:
    settings = settings or CollectorSettings()
    if host is None:
        from thursday_metrics_collector.infrastructure.host import HostReader

        host = HostReader()
    targets = [
        Target(ServiceName.GATEWAY.value, f"http://{LOCALHOST}:{settings.gateway_localhost_port}"),
        Target(ServiceName.VOICE_AGENT.value, f"http://{LOCALHOST}:{settings.voice_agent_port}"),
        Target(ServiceName.MAIN_AGENT.value, f"http://{LOCALHOST}:{settings.main_agent_port}"),
        Target(ServiceName.SPEECH.value, f"http://{LOCALHOST}:{settings.speech_port}"),
    ]
    collector = Collector(
        host,
        targets,
        f"http://{LOCALHOST}:{settings.gateway_localhost_port}",
        settings.thursday_service_token.get_secret_value(),
    )

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        stop = asyncio.Event()
        loop = asyncio.create_task(collector.run(stop, settings.metrics_sample_interval_seconds))
        try:
            yield
        finally:
            stop.set()
            await loop

    app = FastAPI(
        title="Thursday metrics collector", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan
    )
    app.include_router(build_health_router(SERVICE, __version__))

    @app.get("/metrics")
    async def own_metrics() -> dict[str, Any]:
        return {"pushes_failed": collector.pushes_failed}

    return app


def run() -> None:
    settings = CollectorSettings()
    configure_logging(SERVICE.value, log_dir(settings.thursday_data_dir), settings.log_level)
    serve(create_app(settings), settings.metrics_collector_port, settings.log_level)
