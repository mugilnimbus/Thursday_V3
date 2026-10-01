"""Provider interface and the two providers: LM Studio (chat plus model lifecycle) and
generic OpenAI-compatible (chat only).

Model loading is explicit. An already-loaded model is adopted as is; loading it again
would create a second instance (verified in spike S4). JIT loading is never relied on.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from thursday_llm.config import LlmConfig, LoadParameters

log = logging.getLogger(__name__)
LOAD_TIMEOUT_SECONDS = 900.0


class ProviderError(Exception):
    """The endpoint refused or failed a lifecycle request."""


@dataclass(frozen=True, slots=True)
class ModelInfo:
    key: str
    loaded: bool
    max_context_length: int | None
    trained_for_tool_use: bool | None


@dataclass(frozen=True, slots=True)
class LoadedModel:
    key: str
    instance_id: str | None
    context_length: int | None
    adopted: bool
    load_seconds: float | None = None


class Provider(Protocol):
    @property
    def supports_lifecycle(self) -> bool: ...

    async def list_models(self) -> list[ModelInfo]: ...

    async def ensure_loaded(self) -> LoadedModel: ...

    async def unload(self) -> None: ...

    async def reload(self, load: LoadParameters | None = None) -> LoadedModel: ...

    async def reachable(self) -> bool: ...

    async def aclose(self) -> None: ...


def _headers(config: LlmConfig) -> dict[str, str]:
    key = config.api_key.get_secret_value()
    return {"Authorization": f"Bearer {key}"} if key else {}


class OpenAICompatibleProvider:
    """Chat only: no lifecycle, context window unknown."""

    def __init__(self, config: LlmConfig, client: httpx.AsyncClient | None = None) -> None:
        self._config = config
        self._client = client or httpx.AsyncClient(
            base_url=config.base_url.rstrip("/"), headers=_headers(config), timeout=15
        )

    @property
    def supports_lifecycle(self) -> bool:
        return False

    async def list_models(self) -> list[ModelInfo]:
        response = await self._client.get("/v1/models")
        response.raise_for_status()
        return [ModelInfo(m["id"], True, None, None) for m in response.json().get("data", [])]

    async def ensure_loaded(self) -> LoadedModel:
        return LoadedModel(self._config.model, None, None, adopted=True)

    async def unload(self) -> None:
        return None

    async def reload(self, load: LoadParameters | None = None) -> LoadedModel:
        return await self.ensure_loaded()

    async def reachable(self) -> bool:
        try:
            await self.list_models()
        except (httpx.HTTPError, ValueError):
            return False
        return True

    async def aclose(self) -> None:
        await self._client.aclose()


class LmStudioProvider:
    """LM Studio native REST API for lifecycle; chat goes through `/v1/responses` elsewhere."""

    def __init__(self, config: LlmConfig, client: httpx.AsyncClient | None = None) -> None:
        self._config = config
        self._client = client or httpx.AsyncClient(
            base_url=config.base_url.rstrip("/"), headers=_headers(config), timeout=15
        )
        self._lock = asyncio.Lock()
        self._loaded: LoadedModel | None = None

    @property
    def supports_lifecycle(self) -> bool:
        return True

    async def _models_raw(self) -> list[dict]:
        response = await self._client.get("/api/v1/models")
        response.raise_for_status()
        return response.json().get("models", [])

    async def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo(
                m["key"],
                bool(m.get("loaded_instances")),
                m.get("max_context_length"),
                (m.get("capabilities") or {}).get("trained_for_tool_use"),
            )
            for m in await self._models_raw()
            if m.get("type") == "llm"
        ]

    async def _find_loaded(self) -> LoadedModel | None:
        for model in await self._models_raw():
            if model.get("key") == self._config.model and model.get("loaded_instances"):
                instance = model["loaded_instances"][0]
                return LoadedModel(
                    self._config.model,
                    instance.get("id"),
                    (instance.get("config") or {}).get("context_length"),
                    adopted=True,
                )
        return None

    async def ensure_loaded(self) -> LoadedModel:
        """Adopt the loaded instance, or load one with the configured parameters. Concurrent callers wait."""
        async with self._lock:
            found = await self._find_loaded()
            if found is not None:
                self._loaded = found
                return found
            return await self._load(self._config.load)

    async def _load(self, load: LoadParameters) -> LoadedModel:
        body = {"model": self._config.model, "echo_load_config": True, **load.as_request()}
        log.info("loading model %s with %s", self._config.model, load.as_request())
        try:
            response = await self._client.post("/api/v1/models/load", json=body, timeout=LOAD_TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:
            raise ProviderError(f"load request failed: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise ProviderError(f"load refused ({response.status_code}): {response.text[:300]}")
        data = response.json()
        self._loaded = LoadedModel(
            self._config.model,
            data.get("instance_id"),
            (data.get("load_config") or {}).get("context_length"),
            adopted=False,
            load_seconds=data.get("load_time_seconds"),
        )
        return self._loaded

    async def unload(self) -> None:
        async with self._lock:
            for model in await self._models_raw():
                if model.get("key") != self._config.model:
                    continue
                for instance in model.get("loaded_instances") or []:
                    response = await self._client.post("/api/v1/models/unload", json={"instance_id": instance["id"]})
                    if response.status_code >= 400:
                        raise ProviderError(f"unload refused ({response.status_code})")
            self._loaded = None

    async def reload(self, load: LoadParameters | None = None) -> LoadedModel:
        await self.unload()
        async with self._lock:
            return await self._load(load or self._config.load)

    async def reachable(self) -> bool:
        try:
            await self._models_raw()
        except (httpx.HTTPError, ValueError):
            return False
        return True

    @property
    def loaded(self) -> LoadedModel | None:
        return self._loaded

    async def aclose(self) -> None:
        await self._client.aclose()
