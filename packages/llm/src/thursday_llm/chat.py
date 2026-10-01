"""Chat model factory and stream timing.

Chat uses the OpenAI Responses API through LangChain `ChatOpenAI` (spike S3): reasoning
items are kept as content blocks and sent back with tool calls. Retries are done by the
caller so each attempt can be reported; the client itself never retries.
"""

import time
from dataclasses import dataclass, field

import httpx
from langchain_openai import ChatOpenAI

from thursday_llm.capture import CaptureSink, CaptureTransport
from thursday_llm.config import LlmConfig, ProviderKind
from thursday_llm.providers import LmStudioProvider, OpenAICompatibleProvider, Provider


def make_provider(config: LlmConfig) -> Provider:
    if config.provider is ProviderKind.LMSTUDIO:
        return LmStudioProvider(config)
    return OpenAICompatibleProvider(config)


def make_chat_model(
    config: LlmConfig, capture: CaptureSink | None = None, *, use_previous_response_id: bool = False
) -> ChatOpenAI:
    transport = CaptureTransport(capture) if capture else httpx.AsyncHTTPTransport()
    return ChatOpenAI(
        model=config.model,
        base_url=config.base_url.rstrip("/") + "/v1",
        api_key=config.api_key if config.api_key.get_secret_value() else "not-needed",  # pyright: ignore[reportArgumentType]
        use_responses_api=True,
        output_version="responses/v1",
        use_previous_response_id=use_previous_response_id,
        max_retries=0,
        timeout=config.request_timeout_seconds,
        http_async_client=httpx.AsyncClient(transport=transport, timeout=config.request_timeout_seconds),
    )


@dataclass(slots=True)
class StreamTiming:
    """Time to first token and output tokens per second, measured from our own stream.

    Uses perf_counter: on Windows, monotonic() only ticks every ~15.6 ms, which rounds short
    generations to zero or one tick and inflates the token rate.
    """

    started: float = field(default_factory=time.perf_counter)
    first_token_at: float | None = None
    finished_at: float | None = None

    def token_seen(self) -> None:
        if self.first_token_at is None:
            self.first_token_at = time.perf_counter()

    def finish(self) -> None:
        self.finished_at = time.perf_counter()

    @property
    def ttft_seconds(self) -> float | None:
        return None if self.first_token_at is None else self.first_token_at - self.started

    def tokens_per_second(self, output_tokens: int | None) -> float | None:
        if not output_tokens or self.first_token_at is None or self.finished_at is None:
            return None
        generating = self.finished_at - self.first_token_at
        return output_tokens / generating if generating > 0 else None
