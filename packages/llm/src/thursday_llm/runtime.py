"""The LLM settings an agent is running with, changeable at runtime from Settings.

Effective settings = values from `.env` (including the API key, which the UI never writes)
plus non-secret overrides saved by the agent (provider, endpoint, model, load parameters).
Changing them rebuilds the provider and chat client; the next call loads or adopts the model.
"""

import asyncio
import dataclasses
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from thursday_llm.capture import CaptureSink
from thursday_llm.chat import make_chat_model, make_provider
from thursday_llm.config import LlmConfig, LoadParameters, ProviderKind
from thursday_llm.providers import LoadedModel, Provider

BaseConfig = Callable[[], tuple[LlmConfig, str | None]]
"""Returns the `.env` configuration and the name of the variable that supplied the key (or None)."""


class LoadOverrides(BaseModel):
    context_length: int | None = Field(default=None, ge=512, le=2_000_000)
    flash_attention: bool | None = None
    offload_kv_cache_to_gpu: bool | None = None
    eval_batch_size: int | None = Field(default=None, ge=1, le=65536)
    num_experts: int | None = Field(default=None, ge=1, le=256)


class LlmOverrides(BaseModel):
    provider: ProviderKind | None = None
    base_url: str | None = Field(default=None, max_length=500, pattern=r"^https?://")
    model: str | None = Field(default=None, min_length=1, max_length=300)
    load: LoadOverrides = Field(default_factory=LoadOverrides)


class LlmRuntime:
    def __init__(
        self,
        base: BaseConfig,
        load_overrides: Callable[[], dict[str, Any] | None],
        save_overrides: Callable[[dict[str, Any]], None],
        capture: CaptureSink | None = None,
        *,
        fixed_chat: Any = None,
        fixed_provider: Provider | None = None,
    ) -> None:
        self._base = base
        self._save = save_overrides
        self._capture = capture
        self._fixed_chat = fixed_chat
        self._fixed_provider = fixed_provider
        self._overrides = LlmOverrides.model_validate(load_overrides() or {})
        self._lock = asyncio.Lock()
        self.config, self.key_source = self._effective()
        self.provider: Provider = fixed_provider or make_provider(self.config)
        self.chat: Any = fixed_chat or make_chat_model(self.config, capture)

    def _effective(self) -> tuple[LlmConfig, str | None]:
        base, key_source = self._base()
        o = self._overrides
        load = dataclasses.replace(base.load, **o.load.model_dump(exclude_none=True))
        config = dataclasses.replace(
            base,
            provider=o.provider or base.provider,
            base_url=o.base_url or base.base_url,
            model=o.model or base.model,
            load=load,
        )
        return config, key_source

    async def _rebuild(self) -> None:
        self.config, self.key_source = self._effective()
        if self._fixed_provider is None:
            old = self.provider
            self.provider = make_provider(self.config)
            await old.aclose()
        if self._fixed_chat is None:
            self.chat = make_chat_model(self.config, self._capture)

    async def update(self, changes: LlmOverrides) -> None:
        """Apply the fields that were set; `null` in a field clears that override."""
        async with self._lock:
            merged = self._overrides.model_dump()
            data = changes.model_dump(exclude_unset=True)
            merged["load"] = {**merged["load"], **data.pop("load", {})}
            merged.update(data)
            self._overrides = LlmOverrides.model_validate(merged)
            self._save(self._overrides.model_dump(mode="json"))
            await self._rebuild()

    async def reload_keys(self) -> None:
        """Re-read `.env` (keys included) and rebuild."""
        async with self._lock:
            await self._rebuild()

    async def reload_model(self, load: LoadOverrides | None = None) -> LoadedModel:
        if load is not None:
            await self.update(LlmOverrides(load=load))
        return await self.provider.reload()

    def describe(self) -> dict[str, Any]:
        loaded = getattr(self.provider, "loaded", None)
        return {
            "provider": self.config.provider.value,
            "base_url": self.config.base_url,
            "model": self.config.model,
            "load": dataclasses.asdict(self.config.load),
            "api_key_set": bool(self.config.api_key.get_secret_value()),
            "api_key_source": self.key_source,
            "sends_data_off_pc": self.config.sends_data_off_pc,
            "supports_lifecycle": self.provider.supports_lifecycle,
            "loaded": None
            if loaded is None
            else {
                "context_length": loaded.context_length,
                "adopted": loaded.adopted,
                "load_seconds": loaded.load_seconds,
            },
            "overrides": self._overrides.model_dump(mode="json", exclude_none=True),
        }


def config_from_env(
    provider: ProviderKind,
    base_url: str,
    model: str,
    own_key: str,
    own_key_name: str,
    shared_key: str,
    context_length: int | None,
    timeout: float,
) -> tuple[LlmConfig, str | None]:
    """Pick the key: the agent's own variable, else the shared LM Studio token for the LM Studio provider."""
    from pydantic import SecretStr

    key, source = (own_key, own_key_name) if own_key else ("", None)
    if not key and provider is ProviderKind.LMSTUDIO and shared_key:
        key, source = shared_key, "LMSTUDIO_API_TOKEN"
    return LlmConfig(
        provider,
        base_url,
        model,
        SecretStr(key),
        LoadParameters(context_length=context_length),
        request_timeout_seconds=timeout,
    ), source
