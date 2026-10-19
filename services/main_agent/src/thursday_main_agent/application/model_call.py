"""One model reply for a task: load the model, stream the answer, and report every attempt.

A call that brings no reply ends in one of three ways:
- a connection-type error is tried again after a pause, a few times;
- a full window, a cut-off tool call or an empty reply raises `ModelOverflow`: the caller compacts harder and asks
  once more;
- anything else raises `LlmUnavailable`, which fails the task with a message meant for the user.
"""

import asyncio
import re
from contextvars import ContextVar
from typing import Any, Literal, cast

import httpx
import openai
from langchain_core.messages import AIMessage, AIMessageChunk, AnyMessage
from langchain_core.messages.utils import message_chunk_to_message
from thursday_contracts.events import EventType
from thursday_llm.capture import CapturedExchange
from thursday_llm.chat import StreamTiming, stream_timing
from thursday_llm.providers import ProviderError
from thursday_llm.runtime import LlmRuntime
from thursday_llm.stream_reader import read_response

from thursday_main_agent.application.ports import Events
from thursday_main_agent.domain.tasks import TaskRecord

RETRYABLE = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.InternalServerError,
    openai.RateLimitError,
    httpx.HTTPError,
    ProviderError,
)
CONTEXT_FULL = re.compile(r"context (size|length|window)|maximum context|n_ctx|n_keep|too many tokens", re.IGNORECASE)
CUT_OFF_JSON = re.compile(
    r"unterminated string|eof while parsing|invalid json|json_invalid|unexpected end|expecting (value|',')",
    re.IGNORECASE,
)
_CAPTURED: ContextVar[list[CapturedExchange] | None] = ContextVar("thursday_captured", default=None)


def capture_sink(exchange: CapturedExchange) -> None:
    captured = _CAPTURED.get()
    if captured is not None:
        captured.append(exchange)


class LlmUnavailable(Exception):
    """The model cannot be used for this task. The message says why, in words meant for the user."""


Overflow = Literal["context", "truncated", "empty"]
OVERFLOW_MESSAGES: dict[Overflow, str] = {
    "context": (
        "The model ran out of context window, even after the earlier work was compacted harder. "
        "Load the model with a larger context length, or split the work into smaller tasks."
    ),
    "truncated": (
        "The model's reply was cut off in the middle of a tool call, twice in a row. "
        "Load the model with a larger context length, or try the task again."
    ),
    "empty": (
        "The model returned an empty reply twice in a row. Try the task again; "
        "if it keeps happening, load the model with a larger context length."
    ),
}


class ModelOverflow(Exception):
    """One model call went wrong in a way that compacting harder and trying once more can fix."""

    def __init__(self, kind: Overflow, detail: str) -> None:
        super().__init__(detail)
        self.kind: Overflow = kind
        self.detail = detail
        self.attempt = 0  # the attempt number of the call that failed, set by the caller


def classify_error(exc: Exception) -> Literal["context", "truncated"] | None:
    """Whether a model error means the window is full or a tool call was cut off. Mid-stream errors surface as
    plain exceptions with the server's message, so this reads the message."""
    text = str(exc)
    if CONTEXT_FULL.search(text):
        return "context"
    if isinstance(exc, ValueError) and CUT_OFF_JSON.search(text):
        return "truncated"
    return None


def reply_problem(message: AIMessage) -> ModelOverflow | None:
    """A reply that ends the turn badly without raising: a cut-off tool call, an incomplete reply, or nothing."""
    if message.invalid_tool_calls:
        return ModelOverflow("truncated", "a tool call arrived as invalid JSON")
    if message.response_metadata.get("status") == "incomplete":
        reason = (message.response_metadata.get("incomplete_details") or {}).get("reason", "unknown")
        return ModelOverflow("truncated", f"the reply was incomplete ({reason})")
    if not message.tool_calls and not message.text.strip():
        return ModelOverflow("empty", "the model returned an empty reply")
    return None


class ModelCalls:
    """The task runner's way to the model. Remembers the loaded model's window and the last call's speed."""

    def __init__(self, llm: LlmRuntime, events: Events, retries: int, retry_base_delay: float) -> None:
        self._llm = llm
        self._events = events
        self._retries = retries
        self._retry_base_delay = retry_base_delay
        self.context_length: int | None = None
        self.last_llm: dict[str, Any] = {}

    async def note_window(self) -> bool:
        """Make sure the model is loaded and note its context window. False when it cannot be reached right now."""
        try:
            async with self._llm.use():
                loaded = await self._llm.provider.ensure_loaded()
        except RETRYABLE:
            return False
        self.context_length = loaded.context_length or self.context_length
        return True

    async def summarise(self, messages: list[AnyMessage]) -> str:
        chunk: AIMessageChunk | None = None
        async with self._llm.use():
            async for raw in self._llm.chat.astream(messages):
                part = cast(AIMessageChunk, raw)
                chunk = part if chunk is None else chunk + part  # pyright: ignore[reportOperatorIssue]
        return chunk.text if chunk is not None else ""

    async def reply(
        self,
        task: TaskRecord,
        messages: list[AnyMessage],
        tools: list[dict[str, Any]],
        step: int,
        attempt_offset: int = 0,
    ) -> AIMessage:
        """One model reply. The model counts as in use for the whole call, so it is never unloaded under it."""
        async with self._llm.use():
            return await self._attempts(task, messages, tools, step, attempt_offset)

    async def _attempts(
        self,
        task: TaskRecord,
        messages: list[AnyMessage],
        tools: list[dict[str, Any]],
        step: int,
        attempt_offset: int,
    ) -> AIMessage:
        attempts = self._retries + 1
        for attempt in range(1, attempts + 1):
            number = attempt + attempt_offset
            captured: list[CapturedExchange] = []
            token = _CAPTURED.set(captured)
            timing = stream_timing(self._llm.config)
            try:
                loaded = await self._llm.provider.ensure_loaded()
                self.context_length = loaded.context_length
                if not loaded.adopted:
                    self._events.publish(
                        EventType.MODEL_LOAD,
                        {
                            "model": loaded.key,
                            "context_length": loaded.context_length,
                            "load_seconds": loaded.load_seconds,
                        },
                    )
                timing = stream_timing(self._llm.config)  # loading the model is not part of the wait
                chunk: AIMessageChunk | None = None
                async for raw in self._llm.chat.bind_tools(tools).astream(messages):
                    part = cast(AIMessageChunk, raw)
                    timing.piece(part)
                    chunk = part if chunk is None else chunk + part  # pyright: ignore[reportOperatorIssue]
                timing.finish()
                if chunk is None:
                    raise ModelOverflow("empty", "the model returned nothing")
                message = message_chunk_to_message(chunk)
                assert isinstance(message, AIMessage)
                if (problem := reply_problem(message)) is not None:
                    raise problem
                self._publish(task, step, number, "ok", message, timing, captured)
                return message
            except ModelOverflow as exc:
                exc.attempt = number
                self._publish(task, step, number, f"error: {exc.kind}", None, timing, captured, exc.detail)
                raise
            except Exception as exc:  # every model error ends here, so none can leave the task stuck as "working"
                kind = classify_error(exc)
                if kind is not None:
                    self._publish(task, step, number, f"error: {kind}", None, timing, captured, str(exc))
                    overflow = ModelOverflow(kind, str(exc)[:300])
                    overflow.attempt = number
                    raise overflow from exc
                self._publish(task, step, number, f"error: {type(exc).__name__}", None, timing, captured, str(exc))
                if not isinstance(exc, RETRYABLE):
                    if isinstance(exc, openai.APIStatusError):
                        raise LlmUnavailable(f"the model endpoint refused the request ({exc.status_code})") from exc
                    raise LlmUnavailable(f"The model failed: {type(exc).__name__}: {str(exc)[:300]}") from exc
                if attempt == attempts:
                    raise LlmUnavailable(f"the model endpoint failed {attempts} times ({type(exc).__name__})") from exc
                await asyncio.sleep(self._retry_base_delay * 2 ** (attempt - 1))
            finally:
                _CAPTURED.reset(token)
        raise LlmUnavailable("unreachable")

    def _publish(
        self,
        task: TaskRecord,
        step: int,
        attempt: int,
        status: str,
        message: AIMessage | None,
        timing: StreamTiming,
        captured: list[CapturedExchange],
        error: str = "",
    ) -> None:
        usage = dict(message.usage_metadata or {}) if message is not None else {}
        exchange = captured[-1] if captured else None
        tps = timing.tokens_per_second(cast(int | None, usage.get("output_tokens")))
        if message is not None:
            self.last_llm = {
                "llm_ttft_seconds": timing.ttft_seconds,
                "llm_tokens_per_second": tps,
                "llm_input_tokens": usage.get("input_tokens"),
                "context_length": self.context_length,
            }
        self._events.publish(
            EventType.LLM_CALL,
            {
                "agent": "main",
                "step": step,
                "attempt": attempt,
                "status": status,
                "error": error[:500],
                "usage": usage,
                "ttft_seconds": timing.ttft_seconds,
                "tokens_per_second": tps,
                "context_length": self.context_length,
                "tool_calls": [c["name"] for c in message.tool_calls] if message is not None else [],
                "text": message.text if message is not None else "",
                "request_body": exchange.request_body if exchange else None,
                "response_body": read_response(exchange.response_text) if exchange else None,
                "body_truncated": exchange.truncated if exchange else False,
            },
            project_id=task.project_id,
            chat_id=task.chat_id,
            task_id=task.task_id,
        )
