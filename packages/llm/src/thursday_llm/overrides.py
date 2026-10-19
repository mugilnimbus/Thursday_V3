"""What Settings can change about an agent's model, as the agent saves it and as clients send it.

Every field is optional: one that is not set leaves the value from `.env` (or the engine's own default) in place.
"""

from pydantic import BaseModel, Field, SecretStr

from thursday_llm.config import ProviderKind


class LoadOverrides(BaseModel):
    context_length: int | None = Field(default=None, ge=512, le=2_000_000)
    flash_attention: bool | None = None
    offload_kv_cache_to_gpu: bool | None = None
    eval_batch_size: int | None = Field(default=None, ge=1, le=65536)
    num_experts: int | None = Field(default=None, ge=1, le=256)
    moe_cpu_layers: int | None = Field(default=None, ge=0, le=1024)
    gpu_layers: str | None = Field(default=None, pattern=r"^(all|\d{1,3})$")
    gpu_split: str | None = Field(default=None, pattern=r"^\d{1,3}(,\d{1,3}){1,7}$")
    gpu_priority: str | None = Field(default=None, pattern=r"^\d{1,2}(,\d{1,2}){0,7}$")


class InferenceOverrides(BaseModel):
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)
    max_output_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    reasoning: str | None = Field(default=None, pattern=r"^(default|off|on|none|minimal|low|medium|high|xhigh)$")


class Remembered(BaseModel):
    """What a provider was using when the agent last switched away from it."""

    model: str | None = Field(default=None, max_length=300)
    base_url: str | None = Field(default=None, max_length=500)


PER_PROVIDER = ("model", "base_url")


class LlmOverrides(BaseModel):
    provider: ProviderKind | None = None
    base_url: str | None = Field(default=None, max_length=500, pattern=r"^https?://")
    model: str | None = Field(default=None, min_length=1, max_length=300)
    load: LoadOverrides = Field(default_factory=LoadOverrides)
    inference: InferenceOverrides = Field(default_factory=InferenceOverrides)
    models_dir: str | None = Field(default=None, max_length=1000)  # built-in llama.cpp: folder with .gguf files
    gpu: int | None = Field(default=None, ge=0, le=64)
    compact_at_tokens: int | None = Field(default=None, ge=1024, le=2_000_000)
    idle_unload_minutes: float | None = Field(default=None, ge=0, le=1440)  # 0 keeps the model loaded
    remembered: dict[ProviderKind, Remembered] = Field(default_factory=dict)  # kept by the agent, not set by clients
    # The address each stored key was typed for; kept by the agent, not set by clients.
    key_address: dict[ProviderKind, str] = Field(default_factory=dict)


class KeyChange(BaseModel):
    """The API key for the provider in use. An empty value removes the stored key. Never logged or returned."""

    key: SecretStr = Field(max_length=4000)
