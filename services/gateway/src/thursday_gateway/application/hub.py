"""Fan-out of live messages to connected clients.

Each subscriber has a bounded queue. A subscriber that falls too far behind is closed;
the client reconnects with its last position and the gateway replays what it missed.
Messages derived from stored events carry `pos`; ephemeral ones (chat deltas, banners) do not.
"""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from thursday_contracts.events import EventEnvelope, EventType

QUEUE_LIMIT = 1000
KIND_BY_TYPE = {
    EventType.TASK_STATE: "task_state",
    EventType.APPROVAL_REQUESTED: "approval_requested",
    EventType.APPROVAL_RESOLVED: "approval_resolved",
    EventType.NOTIFICATION: "notification",
}


def event_message(pos: int, event: EventEnvelope | dict[str, Any]) -> dict[str, Any]:
    body = event.model_dump(mode="json") if isinstance(event, EventEnvelope) else event
    kind = KIND_BY_TYPE.get(EventType(body["type"]), "timeline_event")
    return {"kind": kind, "pos": pos, "event": body}


def row_message(row: Any) -> dict[str, Any]:
    body = {
        "event_id": row["event_id"],
        "source": row["source"],
        "seq": row["seq"],
        "ts": row["ts"],
        "type": row["type"],
        "project_id": row["project_id"],
        "chat_id": row["chat_id"],
        "task_id": row["task_id"],
        "payload": json.loads(row["payload"]),
    }
    return event_message(row["pos"], body)


@dataclass(eq=False)
class Subscriber:
    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=lambda: asyncio.Queue(QUEUE_LIMIT))
    overflowed: bool = False


class Hub:
    def __init__(self) -> None:
        self._subscribers: set[Subscriber] = set()

    def subscribe(self) -> Subscriber:
        subscriber = Subscriber()
        self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: Subscriber) -> None:
        self._subscribers.discard(subscriber)

    def publish(self, message: dict[str, Any]) -> None:
        for subscriber in list(self._subscribers):
            try:
                subscriber.queue.put_nowait(message)
            except asyncio.QueueFull:
                subscriber.overflowed = True
                self._subscribers.discard(subscriber)

    @property
    def count(self) -> int:
        return len(self._subscribers)
