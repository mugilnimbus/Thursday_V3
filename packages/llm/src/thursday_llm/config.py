"""LLM endpoint configuration for one agent."""

from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import SecretStr


class ProviderKind(StrEnum):
    LMSTUDIO = "lmstudio"
    OPENAI_COMPATIBLE = "openai_compatible"  # a cloud endpoint, or a llama.cpp server you run yourself
    LLAMACPP = "llamacpp"  # llama.cpp that Thursday starts and stops itself, one process per agent


@dataclass(frozen=True, slots=True)
class LoadParameters:
    """LM Studio load parameters. None means "leave LM Studio's default"."""

    context_length: int | None = None
    flash_attention: bool | None = None
    offload_kv_cache_to_gpu: bool | None = None
    eval_batch_size: int | None = None
    num_experts: int | None = None
    moe_cpu_layers: int | None = None  # llama.cpp only: layers whose expert weights stay in system RAM (--n-cpu-moe)
    # llama.cpp only, across the graphics cards it may use. None leaves the choice to llama.cpp, which puts as many
    # layers on the cards as their free memory allows and splits them between the cards by layer. (Its other split
    # modes, "row" and "tensor", fail to load on CUDA in build b11146, so they are not offered.)
    gpu_layers: str | None = None  # "all", or how many layers go on the cards (-ngl)
    gpu_split: str | None = None  # share of the model per card, like "3,1" (--tensor-split)
    # Fill the cards in this order instead of spreading the model over them: "0" fills card 0 first and puts
    # only what does not fit on the next card. Worked out before each load from the cards' free memory.
    gpu_priority: str | None = None

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
class InferenceParameters:
    """How the model answers. None means "leave the server's or the model's default"."""

    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    reasoning: str = "default"  # "default", "off" or "on": whether a thinking model thinks before it answers


@dataclass(frozen=True, slots=True)
class LlamaCppConfig:
    """Where the built-in llama.cpp lives and what it serves. Empty values mean "not set up yet"."""

    server_dir: str = ""  # where `thursday setup` installed llama.cpp (searched for llama-server)
    models_dir: str = ""  # the folder searched for .gguf files
    gpu: int | None = None  # which GPU to use (None: whatever llama.cpp picks)
    log_dir: str = ""
    name: str = "agent"  # which agent this is, for log and pid file names


@dataclass(frozen=True, slots=True)
class LlmConfig:
    provider: ProviderKind
    base_url: str
    model: str
    api_key: SecretStr = field(default_factory=lambda: SecretStr(""))
    load: LoadParameters = field(default_factory=LoadParameters)
    request_timeout_seconds: float = 300.0
    llamacpp: LlamaCppConfig = field(default_factory=LlamaCppConfig)
    inference: InferenceParameters = field(default_factory=InferenceParameters)
    # How many tokens of conversation the agent sends before it shortens the older part. None: decided from the
    # loaded model's window. A cloud endpoint reports no window, so this is the only limit there.
    compact_at_tokens: int | None = None
    # A loaded model that has not been used for this long is unloaded to free the hardware. 0 keeps it loaded.
    idle_unload_minutes: float = 5.0

    @property
    def sends_data_off_pc(self) -> bool:
        """True unless the endpoint is on this machine."""
        if self.provider is ProviderKind.LLAMACPP:
            return False
        host = self.base_url.split("://", 1)[-1].split("/", 1)[0].rsplit(":", 1)[0].strip("[]").lower()
        return host not in {"localhost", "127.0.0.1", "::1"}
