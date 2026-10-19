"""Chat model factory and stream timing.

Chat uses the OpenAI Responses API through LangChain `ChatOpenAI` (spike S3): reasoning
items are kept as content blocks and sent back with tool calls. Retries are done by the
caller so each attempt can be reported; the client itself never retries.
"""

import time
from dataclasses import dataclass, field

import httpx
from langchain_core.messages import AIMessageChunk
from langchain_openai import ChatOpenAI

from thursday_llm.capture import CaptureSink, CaptureTransport
from thursday_llm.config import LlmConfig, ProviderKind

REASONING_EFFORTS = {
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
}  # what Responses endpoints accept; models differ


def make_chat_model(
    config: LlmConfig,
    capture: CaptureSink | None = None,
    *,
    use_previous_response_id: bool = False,
    endpoint: str | None = None,
    api_key: str | None = None,
) -> ChatOpenAI:
    """`endpoint` and `api_key` are given for the built-in llama.cpp, whose address and key exist only once it runs.

    LM Studio and OpenAI-compatible endpoints use the Responses API. The built-in llama.cpp uses chat completions,
    its native API (its `/v1/responses` only converts to it), and switches thinking through the chat template.
    """
    transport = CaptureTransport(capture) if capture else httpx.AsyncHTTPTransport()
    local = config.provider is ProviderKind.LLAMACPP
    secret = api_key if api_key is not None else config.api_key.get_secret_value()
    inference = config.inference
    extra: dict = {}
    if local and inference.reasoning != "default":
        extra["chat_template_kwargs"] = {"enable_thinking": inference.reasoning == "on"}
    return ChatOpenAI(
        model=config.model,
        base_url=((endpoint or config.base_url).rstrip("/")) + "/v1",
        api_key=secret or "not-needed",  # pyright: ignore[reportArgumentType]
        use_responses_api=not local,
        stream_usage=True if local else None,  # chat completions report token counts in a stream only when asked
        output_version="v0" if local else "responses/v1",
        use_previous_response_id=use_previous_response_id,
        temperature=inference.temperature,
        top_p=inference.top_p,
        max_completion_tokens=inference.max_output_tokens,
        extra_body=extra or None,
        reasoning={"effort": inference.reasoning} if not local and inference.reasoning in REASONING_EFFORTS else None,
        max_retries=0,
        timeout=config.request_timeout_seconds,
        http_async_client=httpx.AsyncClient(transport=transport, timeout=config.request_timeout_seconds),
    )


@dataclass(slots=True)
class StreamTiming:
    """Time to first token and output tokens per second, measured from our own stream.

    A model may think before it answers, so two moments are kept. The reply *begins* with the first piece in which
    the model produces anything, thinking included: the token rate runs from there, because the count of output
    tokens includes the thinking. Counted from the first words of the answer instead, a reply that was mostly
    thinking reads many times faster than the model is. The *first token* is the first piece with something in it
    (text, a tool call): the wait before the answer starts.

    Thinking does not always show in a piece. Over chat completions (the built-in llama.cpp) it comes in a field
    the client library does not pass on, so those pieces arrive empty. That server sends nothing before its first
    token, so there (`empty_pieces_count`) an empty piece marks the beginning as well. Over the Responses API the
    stream opens with events that say nothing yet, and thinking arrives as content, so there an empty piece means
    nothing.

    Uses perf_counter: on Windows, monotonic() only ticks every ~15.6 ms, which rounds short
    generations to zero or one tick and inflates the token rate.
    """

    empty_pieces_count: bool = False
    started: float = field(default_factory=time.perf_counter)
    began_at: float | None = None
    first_token_at: float | None = None
    finished_at: float | None = None

    def piece(self, chunk: AIMessageChunk) -> None:
        """Note one piece of the streamed reply as it arrives."""
        if self.first_token_at is not None:
            return
        now = time.perf_counter()
        filled = bool(chunk.content or chunk.tool_call_chunks)
        # The last piece of a chat-completions stream carries only the token counts: it is not the model speaking.
        if self.began_at is None and (filled or (self.empty_pieces_count and chunk.usage_metadata is None)):
            self.began_at = now
        if filled:
            self.first_token_at = now

    def finish(self) -> None:
        self.finished_at = time.perf_counter()

    @property
    def ttft_seconds(self) -> float | None:
        return None if self.first_token_at is None else self.first_token_at - self.started

    def tokens_per_second(self, output_tokens: int | None) -> float | None:
        if not output_tokens or self.began_at is None or self.finished_at is None:
            return None
        generating = self.finished_at - self.began_at
        return output_tokens / generating if generating > 0 else None


def stream_timing(config: LlmConfig) -> StreamTiming:
    """A clock for one streamed reply from this configuration's model, started now."""
    return StreamTiming(empty_pieces_count=config.provider is ProviderKind.LLAMACPP)
