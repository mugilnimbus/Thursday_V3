"""Provider interface and the three providers: LM Studio (chat plus model lifecycle), generic
OpenAI-compatible (chat only; a cloud endpoint or a llama.cpp server you run yourself), and the
built-in llama.cpp (Thursday starts one `llama-server` process per agent and stops it on unload).

Model loading is explicit. An already-loaded model is adopted as is; loading it again
would create a second instance (verified in spike S4). JIT loading is never relied on.
"""

from thursday_llm.config import LlmConfig, ProviderKind
from thursday_llm.providers.base import NO_MODEL, LoadedModel, ModelInfo, Provider, ProviderError
from thursday_llm.providers.llamacpp import LlamaCppProvider
from thursday_llm.providers.lmstudio import LmStudioProvider
from thursday_llm.providers.openai_compatible import OpenAICompatibleProvider

__all__ = [
    "NO_MODEL",
    "LlamaCppProvider",
    "LmStudioProvider",
    "LoadedModel",
    "ModelInfo",
    "OpenAICompatibleProvider",
    "Provider",
    "ProviderError",
    "make_provider",
]


def make_provider(config: LlmConfig) -> Provider:
    if config.provider is ProviderKind.LMSTUDIO:
        return LmStudioProvider(config)
    if config.provider is ProviderKind.LLAMACPP:
        return LlamaCppProvider(config)
    return OpenAICompatibleProvider(config)
