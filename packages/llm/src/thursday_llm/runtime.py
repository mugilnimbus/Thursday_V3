"""The LLM settings an agent is running with, changeable at runtime from Settings.

Effective settings = values from `.env` plus overrides saved by the agent (provider, endpoint, model, load and
inference parameters), plus the API key from the operating system's credential store. A key is kept per provider,
so switching between LM Studio and a cloud endpoint never sends one's key to the other. A key also belongs to the
address it was typed for: when the address changes, the key is held back until it is typed again, so a changed
address never receives a key meant for another server. The model and the endpoint
address are remembered per provider too: a model name from LM Studio means nothing to llama.cpp, so switching
provider brings back what that provider last used, or nothing, never the other provider's values.
Changing them rebuilds the provider and chat client; the next call loads or adopts the model.

A change and a model call never overlap. Rebuilding closes the provider, and for the built-in llama.cpp that stops
the server, so a change asked for while a call is running is refused (`ModelBusy`) and has to be asked again; a
call that starts while a change is being applied waits for it to finish.

The runtime also knows when the model was last used: callers wrap each model call in `use()`, and `idle_loop`
unloads a model nobody has used for the chosen time, so the hardware is free while the services keep running.
"""

import asyncio
import contextlib
import dataclasses
import logging
import time
from collections.abc import AsyncIterator, Callable
from typing import Any, Protocol

from pydantic import SecretStr

from thursday_llm.capture import CaptureSink
from thursday_llm.chat import make_chat_model
from thursday_llm.config import LlamaCppConfig, LlmConfig, LoadParameters, ProviderKind
from thursday_llm.overrides import PER_PROVIDER, LlmOverrides, LoadOverrides
from thursday_llm.providers import LoadedModel, Provider, make_provider

log = logging.getLogger(__name__)

BaseConfig = Callable[[], LlmConfig]
"""Returns the `.env` configuration (no key: keys come from the key store)."""


class KeyStore(Protocol):
    """Where API keys live (the operating system's credential store in production)."""

    def get(self, name: str) -> str: ...

    def set(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...


class ModelBusy(RuntimeError):
    """A change to the model was asked for while it is in use. Nothing was changed; ask again afterwards."""

    def __init__(self) -> None:
        super().__init__("The model is in use right now. Try again when it has finished.")


class LlmRuntime:
    def __init__(
        self,
        base: BaseConfig,
        load_overrides: Callable[[], dict[str, Any] | None],
        save_overrides: Callable[[dict[str, Any]], None],
        capture: CaptureSink | None = None,
        *,
        keys: KeyStore | None = None,
        agent: str = "agent",
        fixed_chat: Any = None,
        fixed_provider: Provider | None = None,
    ) -> None:
        self._base = base
        self._keys = keys
        self._agent = agent
        self._save = save_overrides
        self._capture = capture
        self._fixed_chat = fixed_chat
        self._fixed_provider = fixed_provider
        self._overrides = LlmOverrides.model_validate(load_overrides() or {})
        self._lock = asyncio.Lock()
        self.key_held_back = False
        self.config = self._effective()
        self._adopt_key_address()
        self.provider: Provider = fixed_provider or make_provider(self.config)
        self._chat: Any = fixed_chat or (
            None if self.config.provider is ProviderKind.LLAMACPP else make_chat_model(self.config, capture)
        )
        self._chat_for: tuple[str | None, str] | None = None
        self._busy = 0
        self._last_used = time.monotonic()

    # --- use and idleness ------------------------------------------------------------------------------------
    @contextlib.asynccontextmanager
    async def use(self) -> AsyncIterator[None]:
        """Wrap every model call (loading included) in this, so neither an idle unload nor a change to the settings
        lands in the middle of one. A change that is being applied finishes before the call starts."""
        async with self._lock:
            self._busy += 1
        try:
            yield
        finally:
            self._busy -= 1
            self._last_used = time.monotonic()

    @property
    def idle_seconds(self) -> float:
        return 0.0 if self._busy else time.monotonic() - self._last_used

    async def unload_if_idle(self) -> bool:
        """Unload the model when it is loaded, not in use, and has been idle for the chosen time. True if it did."""
        minutes = self.config.idle_unload_minutes
        if not minutes or self._busy or not self.provider.supports_lifecycle:
            return False
        if getattr(self.provider, "loaded", None) is None or self.idle_seconds < minutes * 60:
            return False
        await self.provider.unload()
        log.info("unloaded %s after %.0f minutes without use", self.config.model, minutes)
        return True

    async def idle_loop(self, stop: asyncio.Event, every: float = 15.0) -> None:
        """Run for the life of the service: look every few seconds for a model to unload."""
        while not stop.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=every)
            try:
                await self.unload_if_idle()
            except Exception as exc:  # a failed unload is tried again on the next pass
                log.warning("idle unload failed: %s", type(exc).__name__)

    async def hear(self, wav: bytes) -> str | None:
        """The words in a WAV clip as the model hears them, or None when this provider or model cannot hear."""
        hear = getattr(self.provider, "hear", None)
        if hear is None:
            return None
        async with self.use():
            return await hear(wav)

    @property
    def chat(self) -> Any:
        """The chat client. For the built-in llama.cpp it is made once the server runs, for that server's address."""
        if self._fixed_chat is not None:
            return self._fixed_chat
        if self.config.provider is ProviderKind.LLAMACPP:
            endpoint, key = getattr(self.provider, "endpoint", None), getattr(self.provider, "api_key", "")
            if endpoint is None:
                raise RuntimeError("the built-in llama.cpp is not running; load the model first")
            if self._chat is None or self._chat_for != (endpoint, key):
                self._chat = make_chat_model(self.config, self._capture, endpoint=endpoint, api_key=key)
                self._chat_for = (endpoint, key)
        return self._chat

    def _key_name(self, provider: ProviderKind) -> str:
        return f"{self._agent}-llm-{provider.value}"

    @staticmethod
    def _same_address(a: str, b: str) -> bool:
        return a.strip().rstrip("/").lower() == b.strip().rstrip("/").lower()

    def _adopt_key_address(self) -> None:
        """A key stored before addresses were noted belongs to the address in use when it is first seen."""
        provider = self.config.provider
        if self._keys is None or provider is ProviderKind.LLAMACPP or provider in self._overrides.key_address:
            return
        if self._keys.get(self._key_name(provider)):
            self._overrides.key_address[provider] = self.config.base_url
            self._save(self._overrides.model_dump(mode="json"))

    def _effective(self) -> LlmConfig:
        base = self._base()
        o = self._overrides
        load = dataclasses.replace(base.load, **o.load.model_dump(exclude_none=True))
        inference = dataclasses.replace(base.inference, **o.inference.model_dump(exclude_none=True))
        llamacpp = dataclasses.replace(
            base.llamacpp,
            **{k: v for k, v in (("models_dir", o.models_dir), ("gpu", o.gpu)) if v is not None},
        )
        provider = o.provider or base.provider
        # The .env address and model belong to the .env provider; another provider starts with none.
        base_url = o.base_url or (base.base_url if provider is base.provider else "")
        key = ""
        self.key_held_back = False
        if self._keys is not None and provider is not ProviderKind.LLAMACPP:  # the built-in server makes its own
            key = self._keys.get(self._key_name(provider))
            typed_for = o.key_address.get(provider)
            if key and typed_for is not None and not self._same_address(typed_for, base_url):
                key, self.key_held_back = "", True  # typed for another address: not sent to this one
        # The .env key belongs to the .env provider at the .env address, and goes nowhere else.
        env_key = base.api_key if provider is base.provider and self._same_address(base.base_url, base_url) else None
        return dataclasses.replace(
            base,
            provider=provider,
            api_key=SecretStr(key) if key else (env_key or SecretStr("")),
            base_url=base_url,
            model=o.model or (base.model if provider is base.provider else ""),
            load=load,
            inference=inference,
            llamacpp=llamacpp,
            compact_at_tokens=o.compact_at_tokens or base.compact_at_tokens,
            idle_unload_minutes=base.idle_unload_minutes if o.idle_unload_minutes is None else o.idle_unload_minutes,
        )

    async def _rebuild(self) -> None:
        self.config = self._effective()
        if self._fixed_provider is None:
            old = self.provider
            self.provider = make_provider(self.config)
            await old.aclose()
        if self._fixed_chat is None:
            self._chat_for = None
            self._chat = (
                None if self.config.provider is ProviderKind.LLAMACPP else make_chat_model(self.config, self._capture)
            )

    def _refuse_if_busy(self) -> None:
        """Called with the lock held, so no call can start between this check and the change it guards."""
        if self._busy:
            raise ModelBusy

    async def update(self, changes: LlmOverrides) -> None:
        """Apply the fields that were set; `null` in a field clears that override. Raises `ModelBusy`, with nothing
        changed, while the model is in use."""
        async with self._lock:
            self._refuse_if_busy()
            await self._apply(changes)

    async def _apply(self, changes: LlmOverrides) -> None:
        merged = self._overrides.model_dump()
        data = changes.model_dump(exclude_unset=True)
        merged["load"] = {**merged["load"], **data.pop("load", {})}
        merged["inference"] = {**merged["inference"], **data.pop("inference", {})}
        data.pop("remembered", None)
        data.pop("key_address", None)
        new = (data["provider"] or self._base().provider) if "provider" in data else self.config.provider
        if new is not self.config.provider:
            # Put away what this provider was using, and bring back what the new one used last.
            remembered = dict(merged["remembered"])
            remembered[self.config.provider] = {k: merged.get(k) for k in PER_PROVIDER}
            restored = remembered.get(new) or {}
            merged["remembered"] = remembered
            for field in PER_PROVIDER:
                if field not in data:  # not chosen in this same change
                    merged[field] = restored.get(field)
        merged.update(data)
        self._overrides = LlmOverrides.model_validate(merged)
        self._save(self._overrides.model_dump(mode="json"))
        await self._rebuild()
        self._adopt_key_address()

    async def set_key(self, value: str) -> None:
        """Store the API key for the provider in use (an empty value removes it), then rebuild. Raises `ModelBusy`,
        with nothing changed, while the model is in use."""
        if self._keys is None:
            raise RuntimeError("no key store")
        async with self._lock:
            self._refuse_if_busy()
            name = self._key_name(self.config.provider)
            if value:
                await asyncio.to_thread(self._keys.set, name, value)
                self._overrides.key_address[self.config.provider] = self.config.base_url  # the address it is for
            else:
                await asyncio.to_thread(self._keys.delete, name)
                self._overrides.key_address.pop(self.config.provider, None)
            self._save(self._overrides.model_dump(mode="json"))
            await self._rebuild()

    async def reload_model(self, load: LoadOverrides | None = None) -> LoadedModel:
        """Load the model afresh, with new load settings when given. Raises `ModelBusy` while it is in use.
        Reloading counts as a use: the idle time starts over when it is done."""
        async with self._lock:
            self._refuse_if_busy()
            if load is not None:
                await self._apply(LlmOverrides(load=load))
            self._busy += 1
            try:
                return await self.provider.reload()
            finally:
                self._busy -= 1
                self._last_used = time.monotonic()

    async def unload_model(self) -> None:
        """Free the hardware now. Raises `ModelBusy` while the model is in use: stopping a task is what ends a
        call, not taking its model away."""
        async with self._lock:
            self._refuse_if_busy()
            await self.provider.unload()

    def describe(self) -> dict[str, Any]:
        loaded = getattr(self.provider, "loaded", None)
        return {
            "provider": self.config.provider.value,
            "base_url": self.config.base_url,
            "model": self.config.model,
            "load": dataclasses.asdict(self.config.load),
            "inference": dataclasses.asdict(self.config.inference),
            "llamacpp": {
                "installed": bool(getattr(self.provider, "installed", False)),
                "models_dir": self.config.llamacpp.models_dir,
                "gpu": self.config.llamacpp.gpu,
                "devices": list(getattr(self.provider, "cards", [])),
                "placement": getattr(self.provider, "placement", "") if loaded is not None else "",
            },
            "compact_at_tokens": self.config.compact_at_tokens,
            "idle_unload_minutes": self.config.idle_unload_minutes,
            "idle_seconds": round(self.idle_seconds) if loaded is not None else None,
            "hears_audio": bool((getattr(self.provider, "modalities", None) or {}).get("audio")),
            "api_key_set": bool(self.config.api_key.get_secret_value()),
            # A key is stored, but for another address: it is not sent until it is typed again.
            "api_key_held_back": self.key_held_back,
            "sends_data_off_pc": self.config.sends_data_off_pc,
            "supports_lifecycle": self.provider.supports_lifecycle,
            "loaded": None
            if loaded is None
            else {
                "context_length": loaded.context_length,
                "adopted": loaded.adopted,
                "load_seconds": loaded.load_seconds,
            },
            "remembered": {
                kind.value: {k: v for k, v in kept.model_dump().items() if v}
                for kind, kept in self._overrides.remembered.items()
            },
            "overrides": self._overrides.model_dump(mode="json", exclude_none=True),
        }


def config_from_env(
    provider: ProviderKind,
    base_url: str,
    model: str,
    context_length: int | None,
    timeout: float,
    llamacpp: LlamaCppConfig | None = None,
    idle_unload_minutes: float = 5.0,
) -> LlmConfig:
    return LlmConfig(
        provider,
        base_url,
        model,
        load=LoadParameters(context_length=context_length),
        request_timeout_seconds=timeout,
        llamacpp=llamacpp or LlamaCppConfig(),
        idle_unload_minutes=idle_unload_minutes,
    )
