"""The token rate and the wait for the first token, when a model thinks before it answers."""

import asyncio
import json
import re
import time
from typing import Any

import pytest
from langchain_core.messages import AIMessageChunk
from pydantic import SecretStr
from thursday_llm import chat
from thursday_llm.chat import StreamTiming, make_chat_model, stream_timing
from thursday_llm.config import LlmConfig, LoadParameters, ProviderKind


def config(provider: ProviderKind) -> LlmConfig:
    return LlmConfig(  # type: ignore[call-arg]
        provider=provider,
        base_url="http://127.0.0.1:1234",
        model="gemma.gguf",
        api_key=SecretStr("k"),
        load=LoadParameters(context_length=8192),
    )


class Clock:
    """Time that moves only when told to, so a rate can be checked exactly."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.now = 100.0
        monkeypatch.setattr(chat.time, "perf_counter", lambda: self.now)

    def after(self, seconds: float) -> None:
        self.now += seconds


EMPTY = AIMessageChunk(content="")
TEXT = AIMessageChunk(content="Hello")
COUNTS = AIMessageChunk(content="", usage_metadata={"input_tokens": 50, "output_tokens": 300, "total_tokens": 350})


def test_thinking_before_the_answer_counts_toward_the_rate_on_the_built_in_llama_cpp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Clock(monkeypatch)
    timing = StreamTiming(empty_pieces_count=True, started=clock.now)
    clock.after(0.1)  # the prompt is read
    timing.piece(EMPTY)  # the first token: thinking, which arrives empty
    for _ in range(20):
        clock.after(0.1)
        timing.piece(EMPTY)
    clock.after(0.1)
    timing.piece(TEXT)  # 2.1 seconds of thinking, then the answer starts
    clock.after(0.9)
    timing.piece(TEXT)
    timing.piece(COUNTS)
    timing.finish()

    assert timing.ttft_seconds == pytest.approx(2.2), "the wait for the answer includes the thinking"
    assert timing.tokens_per_second(300) == pytest.approx(100), "300 tokens over the 3 seconds the model produced them"
    # Counted from the first words of the answer, the same reply read 333 tokens a second.


def test_a_reply_without_thinking_is_measured_as_before(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock(monkeypatch)
    for empty_pieces_count in (True, False):
        timing = StreamTiming(empty_pieces_count=empty_pieces_count, started=clock.now)
        clock.after(0.25)
        timing.piece(TEXT)
        clock.after(2.0)
        timing.piece(TEXT)
        timing.finish()
        assert timing.ttft_seconds == pytest.approx(0.25)
        assert timing.tokens_per_second(200) == pytest.approx(100)


def test_over_the_responses_api_an_empty_piece_is_not_the_model_yet(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock(monkeypatch)
    timing = StreamTiming(started=clock.now)
    timing.piece(AIMessageChunk(content=[]))  # the stream opens before the prompt has been read
    clock.after(1.5)
    timing.piece(AIMessageChunk(content=[{"type": "reasoning", "summary": [], "index": 0}]))  # thinking, as content
    clock.after(1.0)
    timing.piece(AIMessageChunk(content=[{"type": "text", "text": "Hello", "index": 1}]))
    clock.after(1.0)
    timing.finish()
    assert timing.tokens_per_second(200) == pytest.approx(100), "from the thinking on, not from the opening event"
    assert timing.ttft_seconds == pytest.approx(1.5)


def test_a_tool_call_is_the_model_speaking_and_token_counts_alone_are_not(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock(monkeypatch)
    call = AIMessageChunk(content="", tool_call_chunks=[{"name": "fs_read", "args": "{", "id": "c1", "index": 0}])
    timing = StreamTiming(empty_pieces_count=True, started=clock.now)
    clock.after(0.5)
    timing.piece(call)
    clock.after(0.5)
    timing.finish()
    assert timing.ttft_seconds == pytest.approx(0.5) and timing.tokens_per_second(20) == pytest.approx(40)

    only_counts = StreamTiming(empty_pieces_count=True, started=clock.now)
    only_counts.piece(COUNTS)
    only_counts.finish()
    assert only_counts.ttft_seconds is None and only_counts.tokens_per_second(300) is None


def test_no_rate_without_tokens_or_before_the_reply_has_ended(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock(monkeypatch)
    timing = StreamTiming(started=clock.now)
    timing.piece(TEXT)
    assert timing.tokens_per_second(10) is None, "not finished"
    clock.after(1.0)
    timing.finish()
    assert timing.tokens_per_second(None) is None and timing.tokens_per_second(0) is None


def test_the_clock_knows_which_provider_hides_its_thinking() -> None:
    assert stream_timing(config(ProviderKind.LLAMACPP)).empty_pieces_count is True
    assert stream_timing(config(ProviderKind.LMSTUDIO)).empty_pieces_count is False
    assert stream_timing(config(ProviderKind.OPENAI_COMPATIBLE)).empty_pieces_count is False


# --- through the real client -----------------------------------------------------------------------------------


class LlamaCppStandIn:
    """Answers one chat-completions request the way llama.cpp's server streams it: nothing while it reads the
    prompt, then a piece for every token, thinking first (`reasoning_content`), then the answer, then the counts.
    Records when it sent the first piece, the first word of the answer, and the last piece."""

    THINKING, ANSWER, PAUSE, PROMPT = 24, 8, 0.03, 0.2

    def __init__(self) -> None:
        self.first_piece_at = self.first_word_at = self.last_piece_at = 0.0

    def _pieces(self) -> list[dict[str, Any]]:
        def piece(delta: dict[str, Any], finish: str | None = None) -> dict[str, Any]:
            return {
                "id": "chatcmpl-1",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "gemma.gguf",
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }

        thinking = [piece({"role": "assistant", "content": None})]
        thinking += [piece({"reasoning_content": f"hm{n} "}) for n in range(self.THINKING - 1)]
        answer = [piece({"content": f"word{n} "}) for n in range(self.ANSWER)]
        return [*thinking, *answer, piece({}, "stop")]

    async def _answer(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request = b""
        while b"\r\n\r\n" not in request:
            request += await reader.read(65536)
        head, _, body = request.partition(b"\r\n\r\n")
        length = int(re.search(rb"content-length:\s*(\d+)", head.lower()).group(1))  # type: ignore[union-attr]
        while len(body) < length:
            body += await reader.read(65536)

        async def send(data: dict[str, Any] | str) -> None:
            line = f"data: {data if isinstance(data, str) else json.dumps(data)}\n\n".encode()
            writer.write(f"{len(line):x}\r\n".encode() + line + b"\r\n")
            await writer.drain()

        writer.write(
            b"HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\n"
            b"transfer-encoding: chunked\r\nconnection: close\r\n\r\n"
        )
        await writer.drain()
        await asyncio.sleep(self.PROMPT)
        tokens = self.THINKING + self.ANSWER
        for number, piece in enumerate(self._pieces()):
            await asyncio.sleep(self.PAUSE)
            await send(piece)
            if number == 0:
                self.first_piece_at = time.perf_counter()
            if number == self.THINKING:
                self.first_word_at = time.perf_counter()
        self.last_piece_at = time.perf_counter()
        usage = {"prompt_tokens": 50, "completion_tokens": tokens, "total_tokens": 50 + tokens}
        await send({"id": "chatcmpl-1", "object": "chat.completion.chunk", "choices": [], "usage": usage})
        await send("[DONE]")
        writer.write(b"0\r\n\r\n")
        await writer.drain()
        writer.close()

    async def start(self) -> tuple[asyncio.Server, str]:
        server = await asyncio.start_server(self._answer, "127.0.0.1", 0)
        return server, f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"


async def test_a_thinking_reply_from_llama_cpp_is_timed_right_through_the_real_client() -> None:
    stand_in = LlamaCppStandIn()
    server, address = await stand_in.start()
    try:
        llamacpp = config(ProviderKind.LLAMACPP)
        model = make_chat_model(llamacpp, endpoint=address, api_key="k")
        timing = stream_timing(llamacpp)
        sent_at = timing.started
        whole: AIMessageChunk | None = None
        empty_before_the_answer = 0
        async for part in model.astream("hello"):
            assert isinstance(part, AIMessageChunk)
            if whole is None or not whole.content:
                empty_before_the_answer += not part.content
            timing.piece(part)
            whole = part if whole is None else whole + part
        timing.finish()
    finally:
        server.close()
        await server.wait_closed()

    assert whole is not None and whole.usage_metadata is not None
    tokens = whole.usage_metadata["output_tokens"]
    assert tokens == LlamaCppStandIn.THINKING + LlamaCppStandIn.ANSWER
    assert str(whole.content).startswith("word0 "), "the thinking is not part of the text"
    # What this fix rests on: the client hands on a piece for every thinking token, with nothing in it.
    assert empty_before_the_answer >= LlamaCppStandIn.THINKING

    real = tokens / (stand_in.last_piece_at - stand_in.first_piece_at)
    counted_from_the_answer = tokens / (stand_in.last_piece_at - stand_in.first_word_at)
    rate = timing.tokens_per_second(tokens)
    assert rate is not None
    assert rate == pytest.approx(real, rel=0.2), "the rate the server really produced tokens at"
    assert counted_from_the_answer > 2.5 * real and rate < 1.5 * real, "not the rate of the answer's words alone"
    assert timing.ttft_seconds == pytest.approx(stand_in.first_word_at - sent_at, abs=0.15), "the wait for the answer"
