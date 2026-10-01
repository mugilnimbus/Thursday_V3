"""Record raw request and response bodies for traces. Headers are never recorded.

Wraps the httpx transport under the OpenAI client, so it sees exactly what went over the
wire, including streamed responses (the stream is teed while the caller reads it).
"""

import json
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

import httpx

BODY_CHAR_LIMIT = 200_000


@dataclass(slots=True)
class CapturedExchange:
    path: str
    status: int
    request_body: object
    response_text: str
    truncated: bool
    started: float
    finished: float


CaptureSink = Callable[[CapturedExchange], None]


def _cap(text: str) -> tuple[str, bool]:
    return (text, False) if len(text) <= BODY_CHAR_LIMIT else (text[:BODY_CHAR_LIMIT], True)


class CaptureTransport(httpx.AsyncBaseTransport):
    def __init__(self, sink: CaptureSink, inner: httpx.AsyncBaseTransport | None = None) -> None:
        self._sink = sink
        self._inner = inner or httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        started = time.time()
        try:
            request_body: object = json.loads(request.content) if request.content else None
        except ValueError:
            request_body = _cap(request.content.decode("utf-8", errors="replace"))[0]
        response = await self._inner.handle_async_request(request)
        sink = self._sink
        chunks: list[bytes] = []
        size = 0

        class Tee(httpx.AsyncByteStream):
            async def __aiter__(self) -> AsyncIterator[bytes]:
                nonlocal size
                async for chunk in response.stream:  # pyright: ignore[reportGeneralTypeIssues]
                    if size < BODY_CHAR_LIMIT:
                        chunks.append(chunk)
                    size += len(chunk)
                    yield chunk

            async def aclose(self) -> None:
                await response.aclose()
                text, truncated = _cap(b"".join(chunks).decode("utf-8", errors="replace"))
                sink(
                    CapturedExchange(
                        request.url.path,
                        response.status_code,
                        request_body,
                        text,
                        truncated or size > BODY_CHAR_LIMIT,
                        started,
                        time.time(),
                    )
                )

        return httpx.Response(
            response.status_code,
            headers=response.headers,
            stream=Tee(),
            request=request,
            extensions=response.extensions,
        )

    async def aclose(self) -> None:
        await self._inner.aclose()
