"""What every provider offers, and the values the providers and their callers exchange."""

from dataclasses import dataclass
from typing import Protocol

from thursday_llm.config import LlmConfig, LoadParameters

NO_MODEL = "No model is chosen for this agent. Choose one in Settings, Agents."


class ProviderError(Exception):
    """The endpoint refused or failed a lifecycle request."""


@dataclass(frozen=True, slots=True)
class ModelInfo:
    key: str
    loaded: bool
    max_context_length: int | None
    trained_for_tool_use: bool | None
    size_bytes: int | None = None
    projector: str | None = None  # a multimodal projector found beside the model (vision, and audio for some)


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


def auth_headers(config: LlmConfig) -> dict[str, str]:
    key = config.api_key.get_secret_value()
    return {"Authorization": f"Bearer {key}"} if key else {}
