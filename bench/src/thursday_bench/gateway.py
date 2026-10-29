"""What a client of the gateway does: send messages, hold the live stream open, read the monitor.

Everything here goes through the gateway's public client API, on the trusted localhost port.
"""

import asyncio
import contextlib
import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import websockets
from websockets.typing import Origin

from thursday_bench.stack import GATEWAY, PORTS, Stack

HEADERS = {"X-Thursday-Client": "bench"}
PORT = PORTS["GATEWAY_LOCALHOST_PORT"]


@dataclass
class Arrival:
    """One stream message and when it reached us, on the monotonic clock and the wall clock."""

    perf: float
    wall: float
    message: dict[str, Any]

    @property
    def kind(self) -> str:
        return str(self.message.get("kind", ""))

    @property
    def event(self) -> dict[str, Any]:
        return self.message.get("event") or {}

    @property
    def lag_ms(self) -> float | None:
        """Milliseconds from the event's own timestamp to its arrival here (the same machine, so the same clock)."""
        ts = self.event.get("ts")
        if not ts:
            return None
        return (self.wall - datetime.fromisoformat(ts).astimezone(UTC).timestamp()) * 1000


class Stream:
    """The live WebSocket of one chat (or of everything), read into a queue so nothing is missed between reads."""

    def __init__(self, chat_id: str | None, after: int) -> None:
        query = f"after={after}" + (f"&chat_id={chat_id}" if chat_id else "")
        self._url = f"ws://127.0.0.1:{PORT}/v1/stream?{query}"
        self.queue: asyncio.Queue[Arrival] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self.closed_code: int | None = None

    async def __aenter__(self) -> "Stream":
        self._ws = await websockets.connect(self._url, origin=Origin(f"http://127.0.0.1:{PORT}"), max_size=None)
        self._task = asyncio.create_task(self._read())
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        await self._ws.close()

    async def _read(self) -> None:
        try:
            async for raw in self._ws:
                self.queue.put_nowait(Arrival(time.perf_counter(), time.time(), json.loads(raw)))
        except websockets.ConnectionClosed as closed:
            self.closed_code = closed.rcvd.code if closed.rcvd else None

    async def next(self, timeout: float) -> Arrival:
        return await asyncio.wait_for(self.queue.get(), timeout)

    def drain(self) -> list[Arrival]:
        found = []
        while not self.queue.empty():
            found.append(self.queue.get_nowait())
        return found


class Gateway:
    def __init__(self, stack: Stack) -> None:
        self.stack = stack
        self.http = httpx.AsyncClient(base_url=GATEWAY, headers=HEADERS, timeout=30)
        self.project_id = ""

    async def __aenter__(self) -> "Gateway":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.http.aclose()

    async def wait_until_ready(self, seconds: float = 90.0) -> None:
        """The services answer `/health` before the gateway has noticed them. Wait until it shows no banner."""
        deadline = time.monotonic() + seconds
        status: dict[str, Any] = {}
        while time.monotonic() < deadline:
            status = (await self.http.get("/v1/status")).json()
            if not status.get("banners"):
                return
            await asyncio.sleep(0.5)
        raise TimeoutError(f"The gateway still shows a banner after {seconds:.0f} s: {status.get('banners')}")

    async def stream_position(self) -> int:
        return int((await self.http.get("/v1/status")).json()["stream_pos"])

    async def new_chat(self, title: str = "bench") -> str:
        if not self.project_id:
            body = {"name": "bench", "folder": str(self.stack.project_dir)}
            self.project_id = (await self.http.post("/v1/projects", json=body)).json()["project_id"]
        created = await self.http.post(f"/v1/projects/{self.project_id}/chats", json={"title": title})
        return str(created.json()["chat_id"])

    async def send(self, chat_id: str, text: str, message_id: str | None = None) -> httpx.Response:
        body = {"client_message_id": message_id or uuid.uuid4().hex, "text": text}
        return await self.http.post(f"/v1/chats/{chat_id}/messages", json=body)

    async def monitor_latest(self) -> dict[str, Any] | None:
        return (await self.http.get("/v1/monitor", params={"range": "15m"})).json().get("latest")
