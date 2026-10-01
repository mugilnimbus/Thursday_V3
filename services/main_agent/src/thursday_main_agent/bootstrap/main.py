"""Composition root: settings, wiring, background loops, and the HTTP app (A2A + management + health)."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import Field, SecretStr
from pydantic_settings import SettingsConfigDict
from thursday_contracts.events import EventSource
from thursday_contracts.health import ReadinessCheck, ServiceName
from thursday_llm.config import LlmConfig, ProviderKind
from thursday_llm.providers import Provider
from thursday_llm.runtime import LlmRuntime, config_from_env
from thursday_runtime.auth import ServiceTokenAuth
from thursday_runtime.backup import build_backup_router
from thursday_runtime.health import build_health_router
from thursday_runtime.log_setup import configure_logging
from thursday_runtime.outbox import EventPublisher, OutboxSender, OutboxStore
from thursday_runtime.paths import log_dir, service_data_dir
from thursday_runtime.serve import LOCALHOST, serve
from thursday_runtime.settings import CommonSettings, env_file

from thursday_main_agent import __version__
from thursday_main_agent.application.keep_awake import KeepAwake
from thursday_main_agent.application.prompts import DEFAULT_SYSTEM_PROMPT
from thursday_main_agent.application.runner import RunnerSettings, TaskRunner, capture_sink
from thursday_main_agent.application.tasks import TaskService, approval_timer
from thursday_main_agent.infrastructure.mcp_manager import McpManager
from thursday_main_agent.infrastructure.power import WindowsPower
from thursday_main_agent.infrastructure.store import Store
from thursday_main_agent.transport.a2a import A2AServer
from thursday_main_agent.transport.management import Behavior, build_management_router

SERVICE = ServiceName.MAIN_AGENT
log = logging.getLogger(__name__)


class MainAgentSettings(CommonSettings):
    model_config = SettingsConfigDict(
        env_file=env_file(), env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )

    lmstudio_api_token: SecretStr = SecretStr("")
    main_llm_provider: ProviderKind = ProviderKind.LMSTUDIO
    main_llm_base_url: str = "http://localhost:1234"
    main_llm_model: str = ""
    main_llm_api_key: SecretStr = SecretStr("")
    main_llm_context_length: int | None = Field(default=None, ge=512)
    approval_timeout_seconds: int = Field(default=300, ge=5)
    approval_timeouts_before_pause: int = Field(default=2, ge=1)
    llm_retry_count: int = Field(default=3, ge=0, le=10)
    mcp_idle_stop_minutes: float = Field(default=10, gt=0)
    keep_awake_paused_minutes: float = Field(default=30, ge=0)
    compaction_threshold_percent: float = Field(default=90, ge=10, le=99)

    def llm_base(self) -> tuple[LlmConfig, str | None]:
        return config_from_env(
            self.main_llm_provider,
            self.main_llm_base_url,
            self.main_llm_model,
            self.main_llm_api_key.get_secret_value(),
            "MAIN_LLM_API_KEY",
            self.lmstudio_api_token.get_secret_value(),
            self.main_llm_context_length,
            300.0,
        )

    def llm(self) -> LlmConfig:
        return self.llm_base()[0]


@dataclass
class Runtime:
    store: Store
    publisher: EventPublisher
    sender: OutboxSender
    mcp: McpManager
    service: TaskService
    a2a: A2AServer


def create_app(
    settings: MainAgentSettings,
    data_dir: Path,
    *,
    chat_model: Any = None,
    provider: Provider | None = None,
    approval_timeout: timedelta | None = None,
    reread_settings: Callable[[], MainAgentSettings] | None = None,
) -> FastAPI:
    """`chat_model`, `provider`, and `approval_timeout` are injectable for tests. `reread_settings` re-reads
    `.env` when the user asks to reload keys (defaults to the settings given)."""
    store = Store(data_dir / "main_agent.sqlite")
    llm = LlmRuntime(
        lambda: (reread_settings() if reread_settings else settings).llm_base(),
        lambda: store.get_setting("llm"),
        lambda value: store.set_setting("llm", value),
        capture_sink,
        fixed_chat=chat_model,
        fixed_provider=provider,
    )
    outbox = OutboxStore(data_dir / "outbox.sqlite")
    publisher = EventPublisher(outbox, EventSource.MAIN)
    sender = OutboxSender(
        outbox, publisher, f"http://{LOCALHOST}:{settings.gateway_localhost_port}", settings.thursday_service_token
    )
    mcp = McpManager(str(env_file().resolve()), settings.mcp_idle_stop_minutes * 60)
    auth = ServiceTokenAuth(settings.thursday_service_token)
    saved_behavior = store.get_setting("behavior") or {}
    behavior_now = Behavior(
        compaction_threshold_percent=saved_behavior.get(
            "compaction_threshold_percent", settings.compaction_threshold_percent
        ),
        keep_awake_paused_minutes=saved_behavior.get("keep_awake_paused_minutes", settings.keep_awake_paused_minutes),
    )
    keep_awake = KeepAwake(store.open_tasks, WindowsPower(), behavior_now.keep_awake_paused_minutes * 60)
    holder: dict[str, Any] = {}

    def system_prompt() -> str:
        current = store.current_prompt()
        return current[1] if current else DEFAULT_SYSTEM_PROMPT

    async def delete_chat(chat_id: str) -> int:
        task_ids = store.delete_chat(chat_id)
        runtime: Runtime | None = holder.get("runtime")
        if runtime is not None:
            for task_id in task_ids:
                await holder["runner"].forget(task_id)
                with contextlib.suppress(Exception):
                    await runtime.a2a.task_store.delete(task_id, None)  # pyright: ignore[reportArgumentType]
                with contextlib.suppress(Exception):
                    await runtime.a2a.push_store.delete_info(task_id, None)  # pyright: ignore[reportArgumentType]
        outbox.forget(chat_id=chat_id)
        return len(task_ids)

    async def delete_project(project_id: str) -> dict[str, Any]:
        """Delete saga participant for a project: stop its tool server, remove its audit log and its events."""
        stopped = await mcp.stop_project(project_id)
        audit = service_data_dir("tool_server", settings.thursday_data_dir) / f"{project_id}.sqlite"
        removed = []
        for path in (audit, audit.with_name(audit.name + "-wal"), audit.with_name(audit.name + "-shm")):
            with contextlib.suppress(OSError):
                if path.exists():
                    path.unlink()
                    removed.append(path.name)
        return {
            "tool_server_stopped": stopped,
            "audit_files_removed": removed,
            "events": outbox.forget(project_id=project_id),
        }

    def status() -> dict[str, Any]:
        runtime: Runtime | None = holder.get("runtime")
        return {
            "running_tasks": sorted(runtime.service.running) if runtime else [],
            "tool_servers": mcp.status(),
            "gateway_reachable": sender.gateway_reachable,
            "outbox_backlog": outbox.backlog(),
        }

    def metrics() -> dict[str, Any]:
        runtime: Runtime | None = holder.get("runtime")
        runner: TaskRunner | None = holder.get("runner")
        return {
            "running_tasks": len(runtime.service.running) if runtime else 0,
            "open_tasks": len(store.open_tasks()),
            "pending_approvals": len(store.pending_approvals()),
            "outbox_backlog": outbox.backlog(),
            "tool_servers_alive": sum(1 for s in mcp.status().values() if s["alive"]),
            "gateway_reachable": sender.gateway_reachable,
            "keeping_awake": keep_awake.active,
            **(runner.last_llm if runner else {}),
        }

    def behavior() -> Behavior:
        return behavior_now

    def apply_behavior(new: Behavior) -> None:
        nonlocal behavior_now
        behavior_now = new
        store.set_setting("behavior", new.model_dump())
        keep_awake.paused_hold_seconds = new.keep_awake_paused_minutes * 60
        runner: TaskRunner | None = holder.get("runner")
        if runner is not None:
            runner.compaction_threshold_percent = new.compaction_threshold_percent

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
                    compaction_threshold_percent=behavior_now.compaction_threshold_percent,
                ),
                system_prompt,
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
            holder.update(runtime=Runtime(store, publisher, sender, mcp, service, a2a), runner=runner)
            loops = [
                asyncio.create_task(sender.run(stop), name="outbox"),
                asyncio.create_task(approval_timer(service, stop), name="approval-timer"),
                asyncio.create_task(_reaper(mcp, stop), name="mcp-reaper"),
                asyncio.create_task(keep_awake.run(stop), name="keep-awake"),
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
    app.add_api_route("/metrics", metrics, methods=["GET"])
    data_files = ["main_agent.sqlite", "checkpoints.sqlite", "a2a.sqlite", "outbox.sqlite"]
    app.include_router(build_backup_router(SERVICE.value, [data_dir / f for f in data_files], auth))
    app.include_router(
        build_management_router(
            store,
            outbox,
            llm,
            auth,
            delete_chat,
            delete_project,
            status,
            DEFAULT_SYSTEM_PROMPT,
            behavior,
            apply_behavior,
            mcp,
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
            settings, service_data_dir(SERVICE.value, settings.thursday_data_dir), reread_settings=MainAgentSettings
        ),
        settings.main_agent_port,
        settings.log_level,
    )
