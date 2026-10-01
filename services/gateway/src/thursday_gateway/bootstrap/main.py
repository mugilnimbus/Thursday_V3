"""Composition root: shared services, two listeners (localhost trusted, proxy device-token), background loops."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from pydantic_settings import SettingsConfigDict
from thursday_contracts.health import ServiceName
from thursday_runtime.auth import ServiceTokenAuth
from thursday_runtime.health import build_health_router
from thursday_runtime.log_setup import configure_logging
from thursday_runtime.paths import log_dir, service_data_dir
from thursday_runtime.serve import LOCALHOST
from thursday_runtime.settings import CommonSettings, env_file

from thursday_gateway import __version__
from thursday_gateway.application.backup import BackupService, BackupSettings
from thursday_gateway.application.control import TaskControl
from thursday_gateway.application.deletion import DeletionSaga
from thursday_gateway.application.hub import Hub
from thursday_gateway.application.projects import ProjectService
from thursday_gateway.application.relay import MessageRelay
from thursday_gateway.application.status import DependencyStatus
from thursday_gateway.infrastructure.agents import MainAgentClient, VoiceAgentClient
from thursday_gateway.infrastructure.metrics_store import MetricsStore
from thursday_gateway.infrastructure.store import Store
from thursday_gateway.infrastructure.tailnet import TailnetAddress
from thursday_gateway.transport.admin_api import build_admin_router
from thursday_gateway.transport.api import (
    Services,
    build_client_router,
    build_ingest_router,
    install_error_handlers,
    metrics_stream,
    stream,
)
from thursday_gateway.transport.device_auth import DeviceAuth, trusted_local
from thursday_gateway.transport.devices_api import build_claim_router, build_devices_router, build_pairing_router
from thursday_gateway.transport.local_guard import LocalGuard
from thursday_gateway.transport.speech_api import SpeechClient, build_speech_router

SERVICE = ServiceName.GATEWAY
log = logging.getLogger(__name__)


class GatewaySettings(CommonSettings):
    model_config = SettingsConfigDict(
        env_file=env_file(), env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )

    trace_retention_days: int = Field(default=30, ge=1)
    metrics_retention_days: int = Field(default=7, ge=1)
    backup_dir: str = ""
    backup_daily: bool = False
    backup_keep_copies: int = Field(default=7, ge=1)
    dashboard_dir: str = "apps/dashboard/dist"
    dashboard_dev_origins: str = ""  # comma separated, for example http://localhost:5173 while developing
    gateway_public_url: str = ""  # this PC's tailnet HTTPS address; found with `tailscale status` when empty


def build_services(settings: GatewaySettings, data_dir: Path) -> Services:
    store = Store(data_dir / "gateway.sqlite")
    hub = Hub()
    main = MainAgentClient(f"http://{LOCALHOST}:{settings.main_agent_port}", settings.thursday_service_token)
    voice = VoiceAgentClient(f"http://{LOCALHOST}:{settings.voice_agent_port}", settings.thursday_service_token)
    projects = ProjectService(store)
    relay = MessageRelay(store, projects, voice, hub)
    return Services(
        store,
        projects,
        relay,
        TaskControl(store, main),
        DeletionSaga(store, main, voice),
        DependencyStatus(store, main, voice, relay, hub),
        main,
        hub,
        MetricsStore(data_dir / "metrics.sqlite"),
        backup=BackupService(
            store,
            [data_dir / "gateway.sqlite"],
            {
                "main_agent": f"http://{LOCALHOST}:{settings.main_agent_port}",
                "voice_agent": f"http://{LOCALHOST}:{settings.voice_agent_port}",
            },
            settings.thursday_service_token,
            BackupSettings(
                folder=settings.backup_dir, daily=settings.backup_daily, keep_copies=settings.backup_keep_copies
            ),
        ),
        voice=voice,
    )


def create_local_app(s: Services, settings: GatewaySettings) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        stop = asyncio.Event()
        leftovers = s.store.purge_orphans()
        if leftovers:
            log.info("removed %d rows that belonged to deleted chats or projects", leftovers)
        loops = [
            asyncio.create_task(s.relay.run(stop), name="relay"),
            asyncio.create_task(s.deletion.run(stop), name="deletion"),
            asyncio.create_task(s.status.run(stop), name="status"),
            asyncio.create_task(_retention(s, settings, stop), name="retention"),
            *([asyncio.create_task(s.backup.run_daily(stop), name="backup")] if s.backup else []),
        ]
        try:
            yield
        finally:
            stop.set()
            await asyncio.gather(*loops, return_exceptions=True)

    app = FastAPI(title="Thursday gateway", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan)
    install_error_handlers(app)
    app.include_router(build_health_router(SERVICE, __version__))
    app.include_router(build_client_router(s, trusted_local))
    app.include_router(build_ingest_router(s, ServiceTokenAuth(settings.thursday_service_token)))
    app.include_router(build_admin_router(s, trusted_local, retention_defaults(settings)))
    app.include_router(build_pairing_router(s.devices, TailnetAddress(settings.gateway_public_url)))
    app.include_router(build_claim_router(s.devices))
    app.include_router(build_devices_router(s.devices, trusted_local))
    app.include_router(build_speech_router(speech_client(settings), trusted_local))

    @app.websocket("/v1/stream")
    async def ws(websocket: WebSocket, after: int = 0, chat_id: str | None = None) -> None:
        await stream(websocket, s, after, chat_id)

    @app.websocket("/v1/metrics/stream")
    async def ws_metrics(websocket: WebSocket) -> None:
        await metrics_stream(websocket, s)

    @app.get("/metrics")
    async def own_metrics() -> dict[str, object]:
        return {
            "clients_connected": s.hub.count,
            "monitor_clients": s.metrics_hub.count,
            "queued_messages": len(s.store.query("select 1 from outgoing where status = 'queued'")),
            "pending_approvals": len(s.store.query("select 1 from approvals where status = 'pending'")),
            "voice_reachable": s.relay.voice_reachable,
        }

    dist = Path(settings.dashboard_dir)
    if (dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=dist, html=True), name="dashboard")  # last: API routes win
    origins = [o.strip() for o in settings.dashboard_dev_origins.split(",") if o.strip()]
    app.add_middleware(LocalGuard, port=settings.gateway_localhost_port, extra_origins=origins)  # pyright: ignore[reportArgumentType]
    return app


def create_proxy_app(s: Services) -> FastAPI:
    """What tailnet devices reach through the TLS front. Every call needs a device token."""
    devices = DeviceAuth(s.devices)
    app = FastAPI(
        title="Thursday gateway (proxy)", version=__version__, docs_url=None, redoc_url=None, openapi_url=None
    )
    install_error_handlers(app)
    app.include_router(build_client_router(s, devices))
    app.include_router(build_admin_router(s, devices, retention_defaults(GatewaySettings())))
    app.include_router(build_claim_router(s.devices))  # no token yet: the code is the credential
    app.include_router(build_devices_router(s.devices, devices))
    app.include_router(build_speech_router(speech_client(GatewaySettings()), devices))

    @app.websocket("/v1/stream")
    async def ws(websocket: WebSocket, after: int = 0, chat_id: str | None = None) -> None:
        await devices.guard(websocket, stream(websocket, s, after, chat_id))

    @app.websocket("/v1/metrics/stream")
    async def ws_metrics(websocket: WebSocket) -> None:
        await devices.guard(websocket, metrics_stream(websocket, s))

    return app


def speech_client(settings: GatewaySettings) -> SpeechClient:
    return SpeechClient(f"http://{LOCALHOST}:{settings.speech_port}", settings.thursday_service_token)


def retention_defaults(settings: GatewaySettings) -> dict[str, int]:
    return {
        "trace_retention_days": settings.trace_retention_days,
        "metrics_retention_days": settings.metrics_retention_days,
    }


async def _retention(s: Services, settings: GatewaySettings, stop: asyncio.Event) -> None:
    while not stop.is_set():
        days = {**retention_defaults(settings), **(s.store.get_setting("retention") or {})}
        removed = s.store.prune_events(timedelta(days=days["trace_retention_days"]))
        if s.metrics is not None:
            s.metrics.prune(timedelta(days=days["metrics_retention_days"]))
        if removed:
            log.info("retention removed %d old events", removed)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=3600)


def create_app() -> FastAPI:
    """The localhost app alone (used by tests and the launcher's health check)."""
    settings = GatewaySettings()
    return create_local_app(
        build_services(settings, service_data_dir(SERVICE.value, settings.thursday_data_dir)), settings
    )


def run() -> None:
    settings = GatewaySettings()
    configure_logging(SERVICE.value, log_dir(settings.thursday_data_dir), settings.log_level)
    services = build_services(settings, service_data_dir(SERVICE.value, settings.thursday_data_dir))
    level = settings.log_level.lower()
    local = uvicorn.Server(
        uvicorn.Config(
            create_local_app(services, settings),
            host=LOCALHOST,
            port=settings.gateway_localhost_port,
            log_level=level,
            access_log=False,
        )
    )
    proxy = uvicorn.Server(
        uvicorn.Config(
            create_proxy_app(services),
            host=LOCALHOST,
            port=settings.gateway_proxy_port,
            log_level=level,
            access_log=False,
        )
    )

    async def both() -> None:
        await asyncio.gather(local.serve(), proxy.serve())

    asyncio.run(both())
