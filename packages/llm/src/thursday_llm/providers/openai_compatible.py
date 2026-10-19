"""Any OpenAI-compatible endpoint: a cloud service, or a llama.cpp server you run yourself."""

import time

import httpx

from thursday_llm.config import LlmConfig, LoadParameters
from thursday_llm.providers.base import NO_MODEL, LoadedModel, ModelInfo, ProviderError, auth_headers

# Whether the endpoint answers is asked before every turn and by every health check; for a cloud endpoint
# each ask is a request over the internet. A yes is trusted for a while, a no only briefly.
REACHABLE_FOR_SECONDS = 30.0
UNREACHABLE_FOR_SECONDS = 3.0


class OpenAICompatibleProvider:
    """Chat only: no lifecycle, context window unknown."""

    def __init__(self, config: LlmConfig, client: httpx.AsyncClient | None = None) -> None:
        self._config = config
        self._client = client or httpx.AsyncClient(
            base_url=config.base_url.rstrip("/"), headers=auth_headers(config), timeout=15
        )
        self._reachable: tuple[float, bool] | None = None

    @property
    def supports_lifecycle(self) -> bool:
        return False

    async def list_models(self) -> list[ModelInfo]:
        response = await self._client.get("/v1/models")
        response.raise_for_status()
        ids = dict.fromkeys(m["id"] for m in response.json().get("data", []))
        return [ModelInfo(key, True, None, None) for key in ids]

    async def ensure_loaded(self) -> LoadedModel:
        if not self._config.model:
            raise ProviderError(NO_MODEL)
        return LoadedModel(self._config.model, None, None, adopted=True)

    async def unload(self) -> None:
        return None

    async def reload(self, load: LoadParameters | None = None) -> LoadedModel:
        return await self.ensure_loaded()

    async def reachable(self) -> bool:
        now = time.monotonic()
        if self._reachable is not None:
            at, answer = self._reachable
            if now - at < (REACHABLE_FOR_SECONDS if answer else UNREACHABLE_FOR_SECONDS):
                return answer
        try:
            await self.list_models()
            answer = True
        except (httpx.HTTPError, ValueError):
            answer = False
        self._reachable = (now, answer)
        return answer

    async def aclose(self) -> None:
        await self._client.aclose()
