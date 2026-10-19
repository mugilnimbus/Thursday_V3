"""LM Studio: its native REST API loads and unloads models; chat goes through `/v1/responses` elsewhere."""

import asyncio
import logging
import time

import httpx

from thursday_llm.config import LlmConfig, LoadParameters
from thursday_llm.providers.base import NO_MODEL, LoadedModel, ModelInfo, ProviderError, auth_headers

log = logging.getLogger(__name__)
LOAD_TIMEOUT_SECONDS = 900.0
# One model call asks "is it reachable?" and then "is it loaded?", and the task runner asks again a moment
# later. Each was its own request to LM Studio; within this time they share one answer.
MODELS_FRESH_SECONDS = 2.0


class LmStudioProvider:
    """LM Studio native REST API for lifecycle; chat goes through `/v1/responses` elsewhere."""

    def __init__(self, config: LlmConfig, client: httpx.AsyncClient | None = None) -> None:
        self._config = config
        self._client = client or httpx.AsyncClient(
            base_url=config.base_url.rstrip("/"), headers=auth_headers(config), timeout=15
        )
        self._lock = asyncio.Lock()
        self._loaded: LoadedModel | None = None
        self._models: list[dict] = []
        self._models_at: float | None = None

    @property
    def supports_lifecycle(self) -> bool:
        return True

    async def _models_raw(self) -> list[dict]:
        """LM Studio's model list, asked for again once the last answer is a moment old."""
        now = time.monotonic()
        if self._models_at is not None and now - self._models_at < MODELS_FRESH_SECONDS:
            return self._models
        response = await self._client.get("/api/v1/models")
        response.raise_for_status()
        self._models = response.json().get("models", [])
        self._models_at = now
        return self._models

    async def list_models(self) -> list[ModelInfo]:
        # LM Studio lists a model once per downloaded variant, all under the same key; the key is what is loaded.
        models: dict[str, ModelInfo] = {}
        for m in await self._models_raw():
            if m.get("type") != "llm":
                continue
            seen = models.get(m["key"])
            models[m["key"]] = ModelInfo(
                m["key"],
                bool(m.get("loaded_instances")) or (seen is not None and seen.loaded),
                m.get("max_context_length"),
                (m.get("capabilities") or {}).get("trained_for_tool_use"),
            )
        return list(models.values())

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
        if not self._config.model:
            raise ProviderError(NO_MODEL)
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
        self._models_at = None  # what is loaded has changed
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
            self._models_at = None  # what is loaded has changed

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
