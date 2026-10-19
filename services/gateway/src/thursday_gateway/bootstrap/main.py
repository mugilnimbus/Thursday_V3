"""Composition root: shared services, two listeners (localhost trusted, proxy device-token), background loops."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
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
from thursday_runtime.serve import KEEP_ALIVE_SECONDS, LOCALHOST
from thursday_runtime.settings import CommonSettings, env_file
from thursday_runtime.sqlite_care import compact_all

from thursday_gateway import __version__
from thursday_gateway.application.backup import BackupService, BackupSettings
from thursday_gateway.application.control import TaskControl
from thursday_gateway.application.deletion import DeletionSaga
from thursday_gateway.application.devices import DeviceService
from thursday_gateway.application.hub import Hub
from thursday_gateway.application.ingest import EventIngest
from thursday_gateway.application.projects import ProjectService
from thursday_gateway.application.relay import MessageRelay
from thursday_gateway.application.retention import Retention
from thursday_gateway.application.status import DependencyStatus
from thursday_gateway.application.talk_warmup import TalkWarmup
from thursday_gateway.infrastructure.agents import MainAgentClient, VoiceAgentClient
from thursday_gateway.infrastructure.backup_client import ServiceBackups
from thursday_gateway.infrastructure.device_store import DeviceStore
from thursday_gateway.infrastructure.metrics_store import MetricsStore
from thursday_gateway.infrastructure.read_model import ReadModel
from thursday_gateway.infrastructure.speech_client import SpeechClient
from thursday_gateway.infrastructure.store import Store
from thursday_gateway.infrastructure.tailnet import TailnetAddress
from thursday_gateway.transport.admin_api import build_admin_router
from thursday_gateway.transport.api import build_client_router
from thursday_gateway.transport.device_auth import DeviceAuth, trusted_local
from thursday_gateway.transport.devices_api import build_claim_router, build_devices_router, build_pairing_router
from thursday_gateway.transport.errors import install_error_handlers
from thursday_gateway.transport.ingest_api import build_ingest_router
from thursday_gateway.transport.local_guard import LocalGuard
from thursday_gateway.transport.services import Services
from thursday_gateway.transport.speech_api import build_speech_router
from thursday_gateway.transport.streams import metrics_stream, stream

SERVICE = ServiceName.GATEWAY
log = logging.getLogger(__name__)


class GatewaySettings(CommonSettings):
    model_config = SettingsConfigDict(
        env_file=env_file(), env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )

    metrics_retention_days: int = Field(default=7, ge=1)
    backup_dir: str = ""
    backup_daily: bool = False
    backup_keep_copies: int = Field(default=7, ge=1)
    dashboard_dir: str = "apps/dashboard/dist"
    dashboard_dev_origins: str = ""  # comma separated, for example http://localhost:5173 while developing
    gateway_public_url: str = ""  # this PC's tailnet HTTPS address; found with `tailscale status` when empty


def assemble(
    store: Store,
    main: MainAgentClient,
    voice: VoiceAgentClient,
    *,
    retention_defaults: dict[str, int],
    metrics: MetricsStore | None = None,
    backup: BackupService | None = None,
) -> Services:
    """Connect the gateway's logic to its storage and its clients. This is the one place that knows which class
    sits behind each port; tests call it with stand-in clients."""
    hub = Hub()
    read = ReadModel(store)
    relay = MessageRelay(store, voice, hub)
    return Services(
        projects=ProjectService(store),
        relay=relay,
        control=TaskControl(read, main),
        deletion=DeletionSaga(store, main, voice),
        status=DependencyStatus(store, main, voice, relay, hub),
        devices=DeviceService(DeviceStore(store)),
        ingest=EventIngest(store, hub),
        retention=Retention(store, store, metrics, retention_defaults, {"main agent": main, "voice agent": voice}),
        read=read,
        main=main,
        hub=hub,
        metrics=metrics,
        backup=backup,
        voice=voice,
    )


def build_services(settings: GatewaySettings, data_dir: Path) -> Services:
    # Before anything opens them: gives back the space that pruned rows left.
    compact_all([data_dir / "gateway.sqlite", data_dir / "metrics.sqlite"])
    store = Store(data_dir / "gateway.sqlite")
    agents = {
        "main_agent": f"http://{LOCALHOST}:{settings.main_agent_port}",
        "voice_agent": f"http://{LOCALHOST}:{settings.voice_agent_port}",
    }
    token = settings.thursday_service_token
    return assemble(
        store,
        MainAgentClient(agents["main_agent"], token),
        VoiceAgentClient(agents["voice_agent"], token),
        retention_defaults=retention_defaults(settings),
        metrics=MetricsStore(data_dir / "metrics.sqlite"),
        backup=BackupService(
            store,
            [data_dir / "gateway.sqlite"],
            ServiceBackups(agents, token),
            BackupSettings(
                folder=settings.backup_dir, daily=settings.backup_daily, keep_copies=settings.backup_keep_copies
            ),
        ),
    )


def create_local_app(s: Services, settings: GatewaySettings) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        stop = asyncio.Event()
        leftovers = s.retention.remove_orphans()
        if leftovers:
            log.info("removed %d rows that belonged to deleted chats or projects", leftovers)
        loops = [
            asyncio.create_task(s.relay.run(stop), name="relay"),
            asyncio.create_task(s.deletion.run(stop), name="deletion"),
            asyncio.create_task(s.status.run(stop), name="status"),
            asyncio.create_task(s.retention.run(stop), name="retention"),
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
    app.include_router(build_admin_router(s, trusted_local))
    app.include_router(build_pairing_router(s.devices, TailnetAddress(settings.gateway_public_url)))
    app.include_router(build_claim_router(s.devices))
    app.include_router(build_devices_router(s.devices, trusted_local))
    speech = speech_client(settings)
    app.include_router(build_speech_router(speech, trusted_local, s.voice, TalkWarmup(speech, s.voice)))

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
            "queued_messages": s.read.queued_count(),
            "pending_approvals": s.read.pending_approval_count(),
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
    app.include_router(build_admin_router(s, devices))
    app.include_router(build_claim_router(s.devices))  # no token yet: the code is the credential
    app.include_router(build_devices_router(s.devices, devices))
    speech = speech_client(GatewaySettings())
    app.include_router(build_speech_router(speech, devices, s.voice, TalkWarmup(speech, s.voice)))

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
        "data_retention_days": settings.data_retention_days,
        "metrics_retention_days": settings.metrics_retention_days,
    }


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
            timeout_keep_alive=KEEP_ALIVE_SECONDS,
        )
    )
    proxy = uvicorn.Server(
        uvicorn.Config(
            create_proxy_app(services),
            host=LOCALHOST,
            port=settings.gateway_proxy_port,
            log_level=level,
            access_log=False,
            timeout_keep_alive=KEEP_ALIVE_SECONDS,
        )
    )

    async def both() -> None:
        await asyncio.gather(local.serve(), proxy.serve())

    asyncio.run(both())
