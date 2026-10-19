"""One streamed reply from the voice model, reported as an `llm_call` event."""

import time
from collections.abc import AsyncIterator
from typing import Any, cast

from langchain_core.messages import AIMessageChunk, AnyMessage
from langchain_core.messages.utils import message_chunk_to_message
from thursday_contracts.events import EventType
from thursday_llm.chat import stream_timing
from thursday_llm.runtime import LlmRuntime

from thursday_voice_agent.application.ports import Events


class VoiceModelUnavailable(Exception):
    pass


def text_of(chunk: AIMessageChunk) -> str:
    if isinstance(chunk.content, str):
        return chunk.content
    return "".join(b.get("text", "") for b in chunk.content if isinstance(b, dict) and b.get("type") == "text")


class ModelStream:
    """The voice agent's way to its model. Remembers the last call's speed for the service's metrics."""

    def __init__(self, llm: LlmRuntime, events: Events) -> None:
        self._llm = llm
        self._events = events
        self.last_llm: dict[str, Any] = {}

    async def reply(
        self, messages: list[AnyMessage], chat_id: str, project_id: str, tools: list[dict[str, Any]] | None
    ) -> AsyncIterator[tuple[str, Any]]:
        """Yields ("delta", text) as the reply arrives, then ("message", the whole reply). The model counts as in
        use for the whole call, so it is never unloaded under it."""
        async with self._llm.use():
            async for item in self._stream(messages, chat_id, project_id, tools):
                yield item

    async def _stream(
        self, messages: list[AnyMessage], chat_id: str, project_id: str, tools: list[dict[str, Any]] | None
    ) -> AsyncIterator[tuple[str, Any]]:
        loaded = await self._llm.provider.ensure_loaded()
        timing = stream_timing(self._llm.config)
        chunk: AIMessageChunk | None = None
        started = time.perf_counter()
        model = self._llm.chat.bind_tools(tools) if tools else self._llm.chat
        async for raw in model.astream(messages):
            part = cast(AIMessageChunk, raw)
            delta = text_of(part)
            timing.piece(part)
            if delta:
                yield "delta", delta
            chunk = part if chunk is None else chunk + part
        timing.finish()
        if chunk is None:
            raise VoiceModelUnavailable("the voice model returned nothing")
        message = message_chunk_to_message(chunk)
        usage = dict(getattr(message, "usage_metadata", None) or {})
        self._events.publish(
            EventType.LLM_CALL,
            {
                "agent": "voice",
                "status": "ok",
                "usage": usage,
                "ttft_seconds": timing.ttft_seconds,
                "tokens_per_second": timing.tokens_per_second(cast(int | None, usage.get("output_tokens"))),
                "context_length": loaded.context_length,
                "seconds": round(time.perf_counter() - started, 3),
                "text": getattr(message, "text", ""),
                "tool_calls": [c["name"] for c in getattr(message, "tool_calls", [])],
            },
            project_id=project_id,
            chat_id=chat_id,
        )
        self.last_llm = {
            "llm_ttft_seconds": timing.ttft_seconds,
            "context_length": loaded.context_length,
            "llm_tokens_per_second": timing.tokens_per_second(cast(int | None, usage.get("output_tokens"))),
            "llm_input_tokens": usage.get("input_tokens"),
        }
        yield "message", message
