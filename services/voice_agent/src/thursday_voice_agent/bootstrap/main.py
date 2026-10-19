"""Composition root: settings, wiring, background loops, and the HTTP app."""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI
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

from thursday_voice_agent import __version__
from thursday_voice_agent.application.conversation import Conversation
from thursday_voice_agent.application.prompts import SystemPrompt
from thursday_voice_agent.application.retention import WorkingData
from thursday_voice_agent.application.tasks import TaskRelay
from thursday_voice_agent.infrastructure.main_agent import MainAgentClient
from thursday_voice_agent.infrastructure.store import Store
from thursday_voice_agent.transport.http import build_router

SERVICE = ServiceName.VOICE_AGENT


class VoiceAgentSettings(CommonSettings):
    model_config = SettingsConfigDict(
        env_file=env_file(), env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )

    voice_llm_provider: ProviderKind = ProviderKind.LMSTUDIO
    voice_llm_base_url: str = "http://localhost:1234"
    voice_llm_model: str = ""
    voice_llm_context_length: int | None = Field(default=None, ge=512)

    def llm_base(self) -> LlmConfig:
        """The `.env` part of the LLM settings. API keys are not here: they live in the credential store."""
        return config_from_env(
            self.voice_llm_provider,
            self.voice_llm_base_url,
            self.voice_llm_model,
            self.voice_llm_context_length,
            120.0,
            idle_unload_minutes=self.llm_idle_unload_minutes,
            llamacpp=LlamaCppConfig(
                self.llamacpp_dir or str(data_root(self.thursday_data_dir) / "llamacpp"),
                self.llamacpp_models_dir,
                None,
                str(log_dir(self.thursday_data_dir)),
                "voice",
            ),
        )


def create_app(
    settings: VoiceAgentSettings,
    data_dir: Path,
    *,
    chat_model: Any = None,
    provider: Provider | None = None,
    keys: SecretStore | None = None,
    main_client: MainAgentClient | None = None,
    reread_settings: Callable[[], VoiceAgentSettings] | None = None,
) -> FastAPI:
    """Connect the logic to its storage, model, main agent and gateway link, and build the HTTP app.

    `chat_model`, `provider`, and `main_client` are injectable for tests."""
    data_files = [data_dir / "voice_agent.sqlite", data_dir / "outbox.sqlite"]
    compact_all(data_files)  # before anything opens them: gives back the space that pruned rows left
    store = Store(data_dir / "voice_agent.sqlite")
    llm = LlmRuntime(
        lambda: (reread_settings() if reread_settings else settings).llm_base(),
        lambda: store.get_setting("llm"),
        lambda value: store.set_setting("llm", value),
        keys=keys or MemoryStore(),
        agent="voice",
        fixed_chat=chat_model,
        fixed_provider=provider,
    )
    outbox = OutboxStore(data_dir / "outbox.sqlite")
    publisher = EventPublisher(outbox, EventSource.VOICE, deleted=store.chat_deleted)
    sender = OutboxSender(
        outbox, publisher, f"http://{LOCALHOST}:{settings.gateway_localhost_port}", settings.thursday_service_token
    )
    main = main_client or MainAgentClient(
        f"http://{LOCALHOST}:{settings.main_agent_port}", settings.thursday_service_token
    )
    relay = TaskRelay(
        store,
        main,
        publisher,
        f"http://{LOCALHOST}:{settings.voice_agent_port}/v1/push",
        settings.thursday_service_token.get_secret_value(),
    )

    conversation = Conversation(store, relay, llm, publisher, SystemPrompt(store))
    working = WorkingData(store, store, outbox, settings.data_retention_days)
    relay.set_reporter(conversation.report)

    async def llm_ready() -> ReadinessCheck:
        ok = await llm.provider.reachable()
        return ReadinessCheck(ok=ok, detail="" if ok else "voice LLM endpoint unreachable")

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        stop = asyncio.Event()
        loops = [
            asyncio.create_task(sender.run(stop), name="outbox"),
            asyncio.create_task(relay.reconcile(), name="reconcile"),
            asyncio.create_task(llm.idle_loop(stop), name="idle-unload"),
            asyncio.create_task(working.run(stop), name="retention"),
        ]
        try:
            yield
        finally:
            stop.set()
            await relay.close()
            await asyncio.gather(*loops, return_exceptions=True)
            await llm.provider.aclose()
            store.close()
            outbox.close()

    app = FastAPI(title="Thursday voice agent", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.include_router(build_health_router(SERVICE, __version__, {"llm_endpoint": llm_ready}))

    app.include_router(
        build_backup_router(SERVICE.value, data_files, ServiceTokenAuth(settings.thursday_service_token))
    )

    @app.get("/metrics")
    async def metrics() -> dict[str, Any]:
        return {
            "open_tasks": len(store.open_tasks()),
            "outbox_backlog": outbox.backlog(),
            "gateway_reachable": sender.gateway_reachable,
            **conversation.last_llm,
        }

    app.include_router(
        build_router(
            conversation, relay, store, outbox, ServiceTokenAuth(settings.thursday_service_token), llm, working
        )
    )
    return app


def run() -> None:
    settings = VoiceAgentSettings()
    configure_logging(SERVICE.value, log_dir(settings.thursday_data_dir), settings.log_level)
    serve(
        create_app(
            settings,
            service_data_dir(SERVICE.value, settings.thursday_data_dir),
            keys=KeyringStore(),
            reread_settings=VoiceAgentSettings,
        ),
        settings.voice_agent_port,
        settings.log_level,
    )
