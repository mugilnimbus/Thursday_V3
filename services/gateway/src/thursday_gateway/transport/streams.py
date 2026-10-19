"""The WebSocket streams, server to client only: the event stream with replay, and live metrics."""

import asyncio

from fastapi import WebSocket, WebSocketDisconnect

from thursday_gateway.application.hub import row_message
from thursday_gateway.domain.model import valid_id
from thursday_gateway.transport.services import Services

BACKLOG_BATCH = 500


async def metrics_stream(websocket: WebSocket, s: Services) -> None:
    """Live metrics, only while a Monitor screen keeps this socket open."""
    await websocket.accept()
    subscriber = s.metrics_hub.subscribe()
    try:
        latest = s.metrics.latest() if s.metrics else None
        if latest:
            await websocket.send_json({"kind": "metrics", "sample": latest})
        while not subscriber.overflowed:
            await websocket.send_json(await subscriber.queue.get())
        await websocket.close(code=1013)
    except (WebSocketDisconnect, asyncio.CancelledError, RuntimeError):
        pass
    finally:
        s.metrics_hub.unsubscribe(subscriber)


async def stream(websocket: WebSocket, s: Services, after: int, chat_id: str | None) -> None:
    """Replay everything after the client's cursor, then stay live."""
    if chat_id is not None and not valid_id(chat_id):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    subscriber = s.hub.subscribe()  # subscribe first, so nothing falls between backlog and live
    last = after
    try:
        while True:
            rows = s.read.events_after(last, BACKLOG_BATCH, chat_id)
            for row in rows:
                await websocket.send_json(row_message(row))
                last = row["pos"]
            if len(rows) < BACKLOG_BATCH:
                break
        if s.status.current.get("banners"):
            await websocket.send_json({"kind": "status_banner", "banners": s.status.current["banners"]})
        while not subscriber.overflowed:
            message = await subscriber.queue.get()
            pos = message.get("pos")
            if pos is not None and pos <= last:
                continue
            if chat_id is not None and message.get("chat_id", (message.get("event") or {}).get("chat_id")) != chat_id:
                continue
            await websocket.send_json(message)
            if pos is not None:
                last = pos
        await websocket.close(code=1013)  # too far behind: reconnect with the cursor
    except (WebSocketDisconnect, asyncio.CancelledError, RuntimeError):
        pass
    finally:
        s.hub.unsubscribe(subscriber)
