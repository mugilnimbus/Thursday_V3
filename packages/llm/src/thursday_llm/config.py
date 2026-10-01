"""LLM endpoint configuration for one agent."""

from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import SecretStr


class ProviderKind(StrEnum):
    LMSTUDIO = "lmstudio"
    OPENAI_COMPATIBLE = "openai_compatible"


@dataclass(frozen=True, slots=True)
class LoadParameters:
    """LM Studio load parameters. None means "leave LM Studio's default"."""

    context_length: int | None = None
    flash_attention: bool | None = None
    offload_kv_cache_to_gpu: bool | None = None
    eval_batch_size: int | None = None
    num_experts: int | None = None

    def as_request(self) -> dict[str, object]:
        return {
            k: v
            for k, v in (
                ("context_length", self.context_length),
                ("flash_attention", self.flash_attention),
                ("offload_kv_cache_to_gpu", self.offload_kv_cache_to_gpu),
                ("eval_batch_size", self.eval_batch_size),
                ("num_experts", self.num_experts),
            )
            if v is not None
        }


@dataclass(frozen=True, slots=True)
class LlmConfig:
    provider: ProviderKind
    base_url: str
    model: str
    api_key: SecretStr = field(default_factory=lambda: SecretStr(""))
    load: LoadParameters = field(default_factory=LoadParameters)
    request_timeout_seconds: float = 300.0

    @property
    def sends_data_off_pc(self) -> bool:
        """True unless the endpoint is on this machine."""
        host = self.base_url.split("://", 1)[-1].split("/", 1)[0].rsplit(":", 1)[0].strip("[]").lower()
        return host not in {"localhost", "127.0.0.1", "::1"}
