"""A fake OpenAI-compatible model server: streams one fixed reply with no delay.

The agents call it instead of a real model, so the benchmark measures Thursday and not the GPU.
It speaks the Responses API stream (`POST /v1/responses`) and lists one model (`GET /v1/models`).
`GET /_stats` counts the calls it has received, by path.
"""

import json
from collections import Counter
from collections.abc import Iterator
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

MODEL = "bench-fake"
REPLY = "This is a fixed reply from the fake model. It has no delay and never calls a tool. " * 3
PIECES = 24


def _pieces(text: str, count: int) -> list[str]:
    size = max(1, -(-len(text) // count))
    return [text[i : i + size] for i in range(0, len(text), size)]


def _sse(sequence: int, kind: str, **fields: Any) -> str:
    return f"event: {kind}\ndata: {json.dumps({'type': kind, 'sequence_number': sequence, **fields})}\n\n"


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


def stream_reply(input_text: str) -> Iterator[str]:
    """The events of one Responses API stream that carries REPLY."""
    pieces = _pieces(REPLY, PIECES)
    item_id, response_id = "msg_bench", "resp_bench"
    base = {"id": response_id, "object": "response", "model": MODEL, "created_at": 0}
    n = 0
    yield _sse(n, "response.created", response={**base, "status": "in_progress", "output": []})
    n += 1
    item = {"id": item_id, "type": "message", "role": "assistant", "status": "in_progress", "content": []}
    yield _sse(n, "response.output_item.added", output_index=0, item=item)
    n += 1
    part = {"type": "output_text", "text": "", "annotations": []}
    yield _sse(n, "response.content_part.added", item_id=item_id, output_index=0, content_index=0, part=part)
    for piece in pieces:
        n += 1
        yield _sse(n, "response.output_text.delta", item_id=item_id, output_index=0, content_index=0, delta=piece)
    n += 1
    yield _sse(n, "response.output_text.done", item_id=item_id, output_index=0, content_index=0, text=REPLY)
    done_part = {"type": "output_text", "text": REPLY, "annotations": []}
    n += 1
    yield _sse(n, "response.content_part.done", item_id=item_id, output_index=0, content_index=0, part=done_part)
    done_item = {**item, "status": "completed", "content": [done_part]}
    n += 1
    yield _sse(n, "response.output_item.done", output_index=0, item=done_item)
    usage = {
        "input_tokens": _tokens(input_text),
        "output_tokens": _tokens(REPLY),
        "total_tokens": _tokens(input_text) + _tokens(REPLY),
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens_details": {"reasoning_tokens": 0},
    }
    n += 1
    yield _sse(n, "response.completed", response={**base, "status": "completed", "output": [done_item], "usage": usage})


def create_app() -> FastAPI:
    app = FastAPI()
    calls: Counter[str] = Counter()

    @app.get("/v1/models")
    async def models() -> dict[str, Any]:
        calls["GET /v1/models"] += 1
        return {"object": "list", "data": [{"id": MODEL, "object": "model"}]}

    @app.post("/v1/responses")
    async def responses(request: Request) -> StreamingResponse:
        calls["POST /v1/responses"] += 1
        body = await request.json()
        return StreamingResponse(stream_reply(json.dumps(body.get("input", ""))), media_type="text/event-stream")

    @app.get("/_stats")
    async def stats() -> dict[str, int]:
        return dict(calls)

    return app


def serve(port: int) -> None:
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="warning")
