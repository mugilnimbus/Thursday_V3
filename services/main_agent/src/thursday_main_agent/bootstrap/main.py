"""Composition root: settings, wiring, background loops, and the HTTP app (A2A + management + health)."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import Field
from pydantic_settings import SettingsConfigDict
from thursday_contracts.events import EventSource
from thursday_contracts.health import ReadinessCheck, ServiceName
from thursday_llm.config import LlamaCppConfig, LlmConfig, ProviderKind
from thursday_llm.providers import Provider
from thursday_llm.runtime import LlmRuntime, config_from_env
from thursday_runtime.auth import ServiceTokenAuth
from thursday_runtime.backup import build_backup_router
from thursday_runtime.health import build_health_router
from thursday_runtime.log_setup import configure_logging
from thursday_runtime.outbox import EventPublisher, OutboxSender, OutboxStore
from thursday_runtime.paths import data_root, log_dir, service_data_dir
from thursday_runtime.secret_store import KeyringStore, MemoryStore, SecretStore
from thursday_runtime.serve import LOCALHOST, serve
from thursday_runtime.settings import CommonSettings, env_file
from thursday_runtime.sqlite_care import compact_all

from thursday_main_agent import __version__
from thursday_main_agent.application.behavior import Behavior, BehaviorSettings
from thursday_main_agent.application.deletion import Deletion
from thursday_main_agent.application.keep_awake import KeepAwake
from thursday_main_agent.application.model_call import capture_sink
from thursday_main_agent.application.prompts import DEFAULT_SYSTEM_PROMPT, SystemPrompt
from thursday_main_agent.application.retention import WorkingData
from thursday_main_agent.application.runner import RunnerSettings, TaskRunner
from thursday_main_agent.application.status import ServiceStatus
from thursday_main_agent.application.tasks import TaskService, approval_timer
from thursday_main_agent.infrastructure.mcp_manager import McpManager
from thursday_main_agent.infrastructure.power import pick_power
from thursday_main_agent.infrastructure.store import Store
from thursday_main_agent.infrastructure.tool_admin import ToolServerAdmin
from thursday_main_agent.transport.a2a import A2AServer
from thursday_main_agent.transport.management import build_management_router

SERVICE = ServiceName.MAIN_AGENT
log = logging.getLogger(__name__)


class MainAgentSettings(CommonSettings):
    model_config = SettingsConfigDict(
        env_file=env_file(), env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )

    main_llm_provider: ProviderKind = ProviderKind.LMSTUDIO
    main_llm_base_url: str = "http://localhost:1234"
    main_llm_model: str = ""
    main_llm_context_length: int | None = Field(default=None, ge=512)
    approval_timeout_seconds: int = Field(default=300, ge=5)
    approval_timeouts_before_pause: int = Field(default=2, ge=1)
    llm_retry_count: int = Field(default=3, ge=0, le=10)
    mcp_idle_stop_minutes: float = Field(default=10, gt=0)
    keep_awake_paused_minutes: float = Field(default=30, ge=0)
    compaction_threshold_percent: float = Field(default=90, ge=10, le=99)

    def llm_base(self) -> LlmConfig:
        """The `.env` part of the LLM settings. API keys are not here: they live in the credential store."""
        return config_from_env(
            self.main_llm_provider,
            self.main_llm_base_url,
            self.main_llm_model,
            self.main_llm_context_length,
            300.0,
            idle_unload_minutes=self.llm_idle_unload_minutes,
            llamacpp=LlamaCppConfig(
                self.llamacpp_dir or str(data_root(self.thursday_data_dir) / "llamacpp"),
                self.llamacpp_models_dir,
                None,
                str(log_dir(self.thursday_data_dir)),
                "main",
            ),
        )


def create_app(
    settings: MainAgentSettings,
    data_dir: Path,
    *,
    chat_model: Any = None,
    provider: Provider | None = None,
    keys: SecretStore | None = None,
    approval_timeout: timedelta | None = None,
    reread_settings: Callable[[], MainAgentSettings] | None = None,
) -> FastAPI:
    """Connect the logic to its storage, model, tool servers and gateway link, and build the HTTP app.

    `chat_model`, `provider`, and `approval_timeout` are injectable for tests. `reread_settings` re-reads `.env`
    when the user asks to reload keys (defaults to the settings given)."""
    data_files = [
        data_dir / name for name in ("main_agent.sqlite", "checkpoints.sqlite", "a2a.sqlite", "outbox.sqlite")
    ]
    compact_all(data_files)  # before anything opens them: gives back the space that pruned rows left
    store = Store(data_dir / "main_agent.sqlite")
    llm = LlmRuntime(
        lambda: (reread_settings() if reread_settings else settings).llm_base(),
        lambda: store.get_setting("llm"),
        lambda value: store.set_setting("llm", value),
        capture_sink,
        keys=keys or MemoryStore(),
        agent="main",
        fixed_chat=chat_model,
        fixed_provider=provider,
    )
    outbox = OutboxStore(data_dir / "outbox.sqlite")
    publisher = EventPublisher(outbox, EventSource.MAIN, deleted=store.chat_deleted)
    sender = OutboxSender(
        outbox, publisher, f"http://{LOCALHOST}:{settings.gateway_localhost_port}", settings.thursday_service_token
    )
    working = WorkingData(store, store, outbox, settings.data_retention_days)
    env_path = str(env_file().resolve())
    mcp = McpManager(env_path, settings.mcp_idle_stop_minutes * 60, lambda: working.days)
    auth = ServiceTokenAuth(settings.thursday_service_token)
    keep_awake = KeepAwake(store.open_tasks, pick_power(), settings.keep_awake_paused_minutes * 60)
    behavior = BehaviorSettings(
        store,
        keep_awake,
        Behavior(
            compaction_threshold_percent=settings.compaction_threshold_percent,
            keep_awake_paused_minutes=settings.keep_awake_paused_minutes,
        ),
    )
    deletion = Deletion(store, outbox, mcp, ToolServerAdmin(env_path))
    status = ServiceStatus(store, outbox, sender, mcp, keep_awake)

    async def llm_ready() -> ReadinessCheck:
        ok = await llm.provider.reachable()
        return ReadinessCheck(ok=ok, detail="" if ok else "LLM endpoint unreachable")

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        stop = asyncio.Event()
        async with AsyncSqliteSaver.from_conn_string(str(data_dir / "checkpoints.sqlite")) as checkpointer:
            runner = TaskRunner(
                store,
                publisher,
                mcp,
                llm,
                checkpointer,
                RunnerSettings(
                    approval_timeout or timedelta(seconds=settings.approval_timeout_seconds),
                    settings.llm_retry_count,
                    compaction_threshold_percent=behavior.current().compaction_threshold_percent,
                ),
                SystemPrompt(store),
            )
            service = TaskService(store, publisher, runner, settings.approval_timeouts_before_pause)
            a2a = A2AServer(
                service,
                store,
                f"sqlite+aiosqlite:///{(data_dir / 'a2a.sqlite').as_posix()}",
                f"http://{LOCALHOST}:{settings.main_agent_port}",
                settings.thursday_service_token,
                __version__,
            )
            await a2a.initialize()
            service.set_kick(a2a.kick)
            app.router.routes.extend(a2a.routes())
            # These three exist from here on; the services built above use them once they are attached.
            deletion.attach(runner, a2a)
            working.attach(runner, a2a)
            status.attach(service, runner)
            behavior.attach(runner)
            loops = [
                asyncio.create_task(sender.run(stop), name="outbox"),
                asyncio.create_task(approval_timer(service, stop), name="approval-timer"),
                asyncio.create_task(_reaper(mcp, stop), name="mcp-reaper"),
                asyncio.create_task(keep_awake.run(stop), name="keep-awake"),
                asyncio.create_task(llm.idle_loop(stop), name="idle-unload"),
                asyncio.create_task(working.run(stop), name="retention"),
            ]
            for task in service.recoverable():
                log.info("recovering task %s", task.task_id, extra={"task_id": task.task_id})
                asyncio.create_task(service.kick(task.task_id, "recover"))  # noqa: RUF006 - fire and forget
            try:
                yield
            finally:
                stop.set()
                await asyncio.gather(*loops, return_exceptions=True)
                await a2a.aclose()
                await mcp.close()
                await llm.provider.aclose()
                store.close()
                outbox.close()

    app = FastAPI(title="Thursday main agent", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.include_router(build_health_router(SERVICE, __version__, {"llm_endpoint": llm_ready}))
    app.add_api_route("/metrics", status.metrics, methods=["GET"])
    app.include_router(build_backup_router(SERVICE.value, data_files, auth))
    app.include_router(
        build_management_router(
            store, outbox, llm, auth, deletion, status, behavior, working, DEFAULT_SYSTEM_PROMPT, mcp
        )
    )
    return app


async def _reaper(mcp: McpManager, stop: asyncio.Event) -> None:
    while not stop.is_set():
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=30)
        await mcp.reap_idle()


def run() -> None:
    settings = MainAgentSettings()
    configure_logging(SERVICE.value, log_dir(settings.thursday_data_dir), settings.log_level)
    serve(
        create_app(
            settings,
            service_data_dir(SERVICE.value, settings.thursday_data_dir),
            keys=KeyringStore(),
            reread_settings=MainAgentSettings,
        ),
        settings.main_agent_port,
        settings.log_level,
    )
