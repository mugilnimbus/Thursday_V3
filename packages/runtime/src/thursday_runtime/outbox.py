"""Transactional outbox for events to the gateway: at least once, ordered by seq.

Each service keeps its own outbox file. `publish` only writes locally, so a service never
waits on the gateway. The sender delivers batches to `POST /v1/events` with the service
token and backs off while the gateway is down. The outbox also serves replay ("my events
since N") so the gateway can rebuild its read model.
"""

import asyncio
import contextlib
import json
import logging
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr
from thursday_contracts.events import EventEnvelope, EventSource, EventType

log = logging.getLogger(__name__)
BATCH = 200
PAYLOAD_TEXT_LIMIT = 20_000


def cap_payload(value: Any) -> Any:
    """Cap long strings anywhere in a payload and mark them truncated."""
    if isinstance(value, str) and len(value) > PAYLOAD_TEXT_LIMIT:
        return value[:PAYLOAD_TEXT_LIMIT] + f"...[truncated {len(value) - PAYLOAD_TEXT_LIMIT} characters]"
    if isinstance(value, dict):
        return {k: cap_payload(v) for k, v in value.items()}
    if isinstance(value, list):
        return [cap_payload(v) for v in value]
    return value


class OutboxStore:
    def __init__(self, path: Path) -> None:
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self._db.execute("pragma journal_mode=wal")
        self._db.execute(
            "create table if not exists outbox (seq integer primary key autoincrement, event text not null,"
            " created_at text not null, sent integer not null default 0)"
        )
        self._db.execute("create index if not exists outbox_unsent on outbox(sent, seq)")

    def add(self, build: Any) -> int:
        """Reserve the next seq and store the event built with it, in one transaction."""
        with self._lock:
            self._db.execute("begin immediate")
            try:
                now = datetime.now(UTC).isoformat()
                seq = int(
                    self._db.execute("insert into outbox (event, created_at) values ('', ?)", (now,)).lastrowid or 0
                )
                self._db.execute("update outbox set event = ? where seq = ?", (build(seq), seq))
            except BaseException:
                self._db.execute("rollback")
                raise
            self._db.execute("commit")
            return seq

    def unsent(self, limit: int) -> list[tuple[int, str]]:
        with self._lock:
            return [
                (r[0], r[1])
                for r in self._db.execute("select seq, event from outbox where sent = 0 order by seq limit ?", (limit,))
            ]

    def mark_sent(self, up_to_seq: int) -> None:
        with self._lock:
            self._db.execute("update outbox set sent = 1 where seq <= ? and sent = 0", (up_to_seq,))

    def after(self, seq: int, limit: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("select event from outbox where seq > ? order by seq limit ?", (seq, limit))
            return [json.loads(r[0]) for r in rows]

    def forget(self, *, chat_id: str | None = None, project_id: str | None = None) -> int:
        """Remove every stored event of a deleted chat or project, sent or not, so a replay cannot bring it back."""
        field, value = ("chat_id", chat_id) if chat_id is not None else ("project_id", project_id)
        if value is None:
            return 0
        with self._lock:
            return self._db.execute(
                f"delete from outbox where json_extract(event, '$.{field}') = ?",  # noqa: S608 - fixed field names
                (value,),
            ).rowcount

    def backlog(self) -> int:
        with self._lock:
            return int(self._db.execute("select count(*) from outbox where sent = 0").fetchone()[0])

    def prune_sent(self, older_than: timedelta) -> int:
        cutoff = (datetime.now(UTC) - older_than).isoformat()
        with self._lock:
            return self._db.execute("delete from outbox where sent = 1 and created_at < ?", (cutoff,)).rowcount

    def close(self) -> None:
        with self._lock:
            self._db.close()


class EventPublisher:
    def __init__(self, outbox: OutboxStore, source: EventSource) -> None:
        self._outbox = outbox
        self._source = source
        self.wakeup = asyncio.Event()

    def publish(
        self,
        type_: EventType,
        payload: dict[str, Any],
        *,
        project_id: str | None = None,
        chat_id: str | None = None,
        task_id: str | None = None,
    ) -> int:
        capped = cap_payload(payload)

        def build(seq: int) -> str:
            return EventEnvelope(
                source=self._source,
                seq=seq,
                ts=datetime.now(UTC),
                project_id=project_id,
                chat_id=chat_id,
                task_id=task_id,
                type=type_,
                payload=capped,
            ).model_dump_json()

        seq = self._outbox.add(build)
        self.wakeup.set()
        return seq


class OutboxSender:
    def __init__(
        self,
        outbox: OutboxStore,
        publisher: EventPublisher,
        gateway_url: str,
        token: SecretStr,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._outbox = outbox
        self._publisher = publisher
        self._url = gateway_url.rstrip("/") + "/v1/events"
        self._client = client or httpx.AsyncClient(timeout=10)
        self._headers = {"Authorization": f"Bearer {token.get_secret_value()}", "Content-Type": "application/json"}
        self.gateway_reachable = False

    async def send_once(self) -> int:
        rows = self._outbox.unsent(BATCH)
        if not rows:
            return 0
        body = '{"events":[' + ",".join(event for _, event in rows) + "]}"
        response = await self._client.post(self._url, content=body, headers=self._headers)
        response.raise_for_status()
        self._outbox.mark_sent(rows[-1][0])
        return len(rows)

    async def run(self, stop: asyncio.Event) -> None:
        delay = 1.0
        while not stop.is_set():
            try:
                sent = await self.send_once()
                self.gateway_reachable = True
                delay = 1.0
                if sent == BATCH:
                    continue
            except (httpx.HTTPError, ValueError) as exc:
                if self.gateway_reachable:
                    log.warning("gateway event ingest unavailable: %s", type(exc).__name__)
                self.gateway_reachable = False
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=delay)
                delay = min(delay * 2, 30.0)
                continue
            self._publisher.wakeup.clear()
            waiters = [asyncio.create_task(stop.wait()), asyncio.create_task(self._publisher.wakeup.wait())]
            try:
                await asyncio.wait(waiters, timeout=2.0, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for waiter in waiters:
                    waiter.cancel()
