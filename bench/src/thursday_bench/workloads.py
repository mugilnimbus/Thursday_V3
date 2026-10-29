"""The seven workloads. Each returns a dict of measured numbers; it never reads service code."""

import asyncio
import contextlib
import os
import pathlib
import random
import statistics
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import psutil

from thursday_bench.gateway import Arrival, Gateway, Stream
from thursday_bench.stack import GATEWAY, PORTS, Stack
from thursday_bench.stats import summary

WARMUP_MESSAGES = 5
REPLY_TIMEOUT = 60.0
VOCABULARY = [f"word{i:03d}" for i in range(200)]
RARE_WORD = "zzrareword"


async def round_trip(gw: Gateway, chat_id: str, stream: Stream, text: str) -> dict[str, Any]:
    """Send one message and follow it to the final reply. Times are in milliseconds."""
    stream.drain()
    start = time.perf_counter()
    message_id = uuid.uuid4().hex
    try:
        response = await gw.send(chat_id, text, message_id)
    except httpx.HTTPError as exc:
        return {"error": type(exc).__name__}
    ack = (time.perf_counter() - start) * 1000
    if response.status_code != 202:
        return {"error": f"http {response.status_code}", "ack_ms": ack}
    row: dict[str, Any] = {"ack_ms": ack, "events": 0, "chat_id": chat_id, "client_message_id": message_id}
    deadline = start + REPLY_TIMEOUT
    while True:
        try:
            arrival = await stream.next(deadline - time.perf_counter())
        except TimeoutError:
            row["error"] = "no reply"
            return row
        if arrival.kind == "chat_delta":
            row.setdefault("first_delta_ms", (arrival.perf - start) * 1000)
        elif arrival.kind == "timeline_event":
            kind = arrival.event.get("type")
            row["events"] += 1
            if kind in ("user_message", "llm_call", "assistant_message") and arrival.lag_ms is not None:
                row.setdefault(f"lag_{kind}_ms", arrival.lag_ms)
            if kind == "assistant_message":
                row["reply_ms"] = (arrival.perf - start) * 1000
                return row


def _column(rows: list[dict[str, Any]], key: str) -> list[float]:
    return [float(r[key]) for r in rows if key in r]


def _latency_summaries(rows: list[dict[str, Any]]) -> dict[str, Any]:
    keys = (
        "ack_ms",
        "first_delta_ms",
        "reply_ms",
        "lag_user_message_ms",
        "lag_llm_call_ms",
        "lag_assistant_message_ms",
    )
    return {key: summary(_column(rows, key)) for key in keys}


async def serial_chat(gw: Gateway, _: Stack, messages: int = 200) -> dict[str, Any]:
    """Workloads 1 to 3: one chat, one message at a time. Send latency, reply latency and event lag."""
    chat = await gw.new_chat()
    async with Stream(chat, await gw.stream_position()) as stream:
        for i in range(WARMUP_MESSAGES):
            await round_trip(gw, chat, stream, f"warm-up {i}")
        rows = [await round_trip(gw, chat, stream, f"message {i}") for i in range(messages)]
    good = [r for r in rows if "error" not in r]
    half = len(good) // 4 or 1
    return {
        "messages": len(rows),
        "errors": len(rows) - len(good),
        **_latency_summaries(good),
        "reply_first_quarter_p50_ms": round(statistics.median(_column(good[:half], "reply_ms") or [float("nan")]), 2),
        "reply_last_quarter_p50_ms": round(statistics.median(_column(good[-half:], "reply_ms") or [float("nan")]), 2),
    }


async def burst(gw: Gateway, _: Stack, messages: int = 120) -> dict[str, Any]:
    """Workload 4: send messages as fast as possible without waiting for replies, until the chat refuses some."""
    chat = await gw.new_chat()
    async with Stream(chat, await gw.stream_position()) as stream:
        accepted: list[str] = []
        refused = 0
        first_refusal: int | None = None
        retry_after = None
        start = time.perf_counter()
        for i in range(messages):
            message_id = f"burst-{i:04d}"
            response = await gw.send(chat, f"burst {i}", message_id)
            if response.status_code == 202:
                accepted.append(message_id)
            elif response.status_code == 429:
                refused += 1
                first_refusal = i if first_refusal is None else first_refusal
                retry_after = response.headers.get("retry-after")
        sending_seconds = time.perf_counter() - start
        delivered_order: list[str] = []
        replies = 0
        deadline = time.perf_counter() + 20 + len(accepted) * 2
        while replies < len(accepted) and time.perf_counter() < deadline:
            try:
                arrival = await stream.next(max(0.1, deadline - time.perf_counter()))
            except TimeoutError:
                break
            if arrival.kind != "timeline_event":
                continue
            kind = arrival.event.get("type")
            if kind == "user_message":
                delivered_order.append(arrival.event["payload"].get("client_message_id", ""))
            elif kind == "assistant_message":
                replies += 1
        total_seconds = time.perf_counter() - start
    return {
        "sent": messages,
        "accepted": len(accepted),
        "refused_429": refused,
        "first_refusal_after": first_refusal if first_refusal is not None else -1,
        "retry_after_seconds": float(retry_after) if retry_after else -1,
        "replies": replies,
        "all_accepted_answered": replies == len(accepted),
        "in_order": delivered_order == accepted,
        "sending_seconds": round(sending_seconds, 3),
        "total_seconds": round(total_seconds, 1),
    }


def service_rss_mb(stack: Stack) -> dict[str, float]:
    sizes: dict[str, float] = {}
    for module, processes in stack.service_processes().items():
        total = 0.0
        for process in processes:
            with contextlib.suppress(psutil.Error):
                total += process.memory_info().rss / 1_048_576
        sizes[module] = round(total, 1)
    return sizes


async def _sample(gw: Gateway, stack: Stack, started: float, series: list[dict[str, Any]]) -> None:
    """Every 5 seconds: memory of each service, and the monitor's own reading."""
    while True:
        point: dict[str, Any] = {"t": round(time.perf_counter() - started, 1), "rss_mb": service_rss_mb(stack)}
        with contextlib.suppress(httpx.HTTPError, ValueError):
            latest = await gw.monitor_latest()
            if latest:
                point["cpu_percent"] = latest["cpu_percent"]
                point["ram_used_mb"] = latest["ram_used_mb"]
                point["outbox_backlog"] = {
                    s["name"]: s["metrics"].get("outbox_backlog") for s in latest["services"] if s["metrics"]
                }
        series.append(point)
        await asyncio.sleep(5)


def _load_summary(rows: list[dict[str, Any]], series: list[dict[str, Any]], seconds: float) -> dict[str, Any]:
    good = [r for r in rows if "error" not in r]
    totals = [sum(p["rss_mb"].values()) for p in series if p["rss_mb"]]
    minute = max(1, 60 // 5)
    backlog = [v for p in series for v in (p.get("outbox_backlog") or {}).values() if isinstance(v, int | float)]
    cpu = [p["cpu_percent"] for p in series if "cpu_percent" in p]
    return {
        "messages": len(rows),
        "errors": len(rows) - len(good),
        "error_kinds": {
            kind: sum(1 for r in rows if r.get("error") == kind) for kind in {r["error"] for r in rows if "error" in r}
        },
        "error_rate_percent": round((len(rows) - len(good)) / len(rows) * 100, 2) if rows else 0,
        "messages_per_second": round(len(good) / seconds, 2),
        "events_per_second": round(sum(r["events"] for r in good) / seconds, 2),
        **_latency_summaries(good),
        "service_rss_mb_first_minute": round(statistics.median(totals[:minute]), 1) if totals else -1,
        "service_rss_mb_last_minute": round(statistics.median(totals[-minute:]), 1) if totals else -1,
        "service_rss_mb_max": round(max(totals), 1) if totals else -1,
        "outbox_backlog_max": max(backlog) if backlog else 0,
        "pc_cpu_percent_median": round(statistics.median(cpu), 1) if cpu else -1,
    }


async def _chat_workers(
    gw: Gateway, chat_ids: list[str], seconds: float, rows: list[dict[str, Any]], sent: dict[str, int]
) -> None:
    position = await gw.stream_position()
    async with contextlib.AsyncExitStack() as stack_:
        streams = {c: await stack_.enter_async_context(Stream(c, position)) for c in chat_ids}
        for chat in chat_ids:
            for i in range(2):
                await round_trip(gw, chat, streams[chat], f"warm-up {i}")
        end = time.perf_counter() + seconds

        async def worker(chat: str) -> None:
            while time.perf_counter() < end:
                row = await round_trip(gw, chat, streams[chat], f"load {uuid.uuid4().hex[:8]}")
                rows.append(row)
                if "error" not in row:
                    sent[chat] = sent.get(chat, 0) + 1

        await asyncio.gather(*(worker(c) for c in chat_ids))


async def many_chats(gw: Gateway, stack: Stack, chats: int = 20, seconds: float = 300) -> dict[str, Any]:
    """Workload 5: many chats send at once. Throughput, errors, memory and backlog."""
    chat_ids = [await gw.new_chat(f"load-{i}") for i in range(chats)]
    rows: list[dict[str, Any]] = []
    series: list[dict[str, Any]] = []
    sampler = asyncio.create_task(_sample(gw, stack, time.perf_counter(), series))
    try:
        await _chat_workers(gw, chat_ids, seconds, rows, {})
    finally:
        sampler.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sampler
    return {"chats": chats, "seconds": seconds, **_load_summary(rows, series, seconds)}


async def _all_events(gw: Gateway) -> list[Arrival]:
    """Every stored event, read from the start of the stream until it goes quiet."""
    found: list[Arrival] = []
    async with Stream(None, 0) as stream:
        while True:
            try:
                found.append(await stream.next(4))
            except TimeoutError:
                return [a for a in found if a.kind != "chat_delta"]


def _integrity(arrivals: list[Arrival], accepted: dict[str, int]) -> dict[str, Any]:
    """Compare the stored events with what was sent: gaps and repeats in `seq`, repeated and missing messages."""
    events = [a.event for a in arrivals if a.event]
    by_source: dict[str, list[int]] = {}
    seen_event_ids: set[str] = set()
    repeated_event_ids = 0
    users: dict[str, int] = {}
    user_events: dict[str, list[str]] = {}
    user_text: dict[str, str] = {}
    for event in events:
        by_source.setdefault(event["source"], []).append(event["seq"])
        if event["event_id"] in seen_event_ids:
            repeated_event_ids += 1
        seen_event_ids.add(event["event_id"])
        if event["type"] == "user_message":
            mid = event["payload"].get("client_message_id", "")
            users[mid] = users.get(mid, 0) + 1
            user_events.setdefault(mid, []).append(
                f"{event['source']}#{event['seq']} {event['ts']} {event['event_id']}"
            )
            user_text[mid] = event["payload"].get("text", "")
    repeated_seq = gaps = 0
    for seqs in by_source.values():
        ordered = sorted(seqs)
        repeated_seq += len(ordered) - len(set(ordered))
        unique = sorted(set(ordered))
        gaps += (unique[-1] - unique[0] + 1) - len(unique) + (unique[0] - 1)
    assistants = sum(1 for e in events if e["type"] == "assistant_message")
    return {
        "events_stored": len(events),
        "seq_gaps": gaps,
        "seq_repeats": repeated_seq,
        "event_id_repeats": repeated_event_ids,
        "user_messages_repeated": sum(1 for n in users.values() if n > 1),
        "repeated_user_message_examples": [user_events[m] for m, n in users.items() if n > 1][:5],
        "repeated_user_message_texts": [user_text[m] for m, n in users.items() if n > 1][:5],
        "assistant_messages": assistants,
        "messages_answered": sum(accepted.values()),
    }


def _unanswered(rows: list[dict[str, Any]], arrivals: list[Arrival]) -> list[dict[str, Any]]:
    """For each round trip that timed out: was the message stored, and was it answered later?"""
    by_chat: dict[str, list[dict[str, Any]]] = {}
    for a in arrivals:
        if a.event and a.event.get("chat_id"):
            by_chat.setdefault(a.event["chat_id"], []).append(a.event)
    report = []
    for row in rows:
        if row.get("error") != "no reply":
            continue
        events = by_chat.get(row["chat_id"], [])
        mine = [
            i
            for i, e in enumerate(events)
            if e["type"] == "user_message" and e["payload"].get("client_message_id") == row["client_message_id"]
        ]
        entry: dict[str, Any] = {"client_message_id": row["client_message_id"], "user_events": len(mine)}
        if mine:
            first = events[mine[0]]
            later = events[mine[0] + 1 :]
            nxt = next((i for i, e in enumerate(later) if e["type"] == "user_message"), len(later))
            answers = [e for e in later[:nxt] if e["type"] == "assistant_message"]
            entry["answered_later"] = bool(answers)
            entry["user_ts"] = first["ts"]
            if answers:
                entry["answer_ts"] = answers[0]["ts"]
        report.append(entry)
    return report


async def soak(gw: Gateway, stack: Stack, chats: int = 20, seconds: float = 1800) -> dict[str, Any]:
    """Workload 7: the load of workload 5 for a long time, one agent killed in the middle, then count what was lost."""
    chat_ids = [await gw.new_chat(f"soak-{i}") for i in range(chats)]
    rows: list[dict[str, Any]] = []
    sent: dict[str, int] = {}
    series: list[dict[str, Any]] = []
    sampler = asyncio.create_task(_sample(gw, stack, time.perf_counter(), series))
    killed: dict[str, Any] = {}

    async def killer() -> None:
        await asyncio.sleep(seconds / 2 + 10)
        victims = stack.service_processes().get("thursday_voice_agent", [])
        if not victims:
            return
        killed["pid"] = victims[0].pid
        at = time.perf_counter()
        for victim in victims:
            with contextlib.suppress(psutil.Error):
                os.kill(victim.pid, 9)
        async with httpx.AsyncClient(timeout=1) as probe:
            while time.perf_counter() - at < 120:
                await asyncio.sleep(0.25)
                with contextlib.suppress(httpx.HTTPError):
                    if (await probe.get(f"http://127.0.0.1:{PORTS['VOICE_AGENT_PORT']}/health")).status_code == 200:
                        killed["back_after_seconds"] = round(time.perf_counter() - at, 2)
                        return

    killer_task = asyncio.create_task(killer())
    try:
        await _chat_workers(gw, chat_ids, seconds, rows, sent)
    finally:
        sampler.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sampler
    await killer_task
    await asyncio.sleep(5)
    arrivals = await _all_events(gw)
    integrity = _integrity(arrivals, sent)
    integrity["unanswered"] = _unanswered(rows, arrivals)
    for entry in integrity["unanswered"]:  # what the gateway and the voice agent say about each one
        chat = next(r["chat_id"] for r in rows if r.get("client_message_id") == entry["client_message_id"])
        pending = (await gw.http.get(f"/v1/chats/{chat}/messages")).json().get("pending", [])
        entry["outgoing"] = [p for p in pending if p.get("client_message_id") == entry["client_message_id"]]
        for name in ("voice_agent.log", "gateway.log"):
            path = stack.data_dir / "logs" / name
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.exists() else []
            entry[name] = [line[:300] for line in lines if entry["client_message_id"] in line][:10]
    for entry in integrity["unanswered"]:  # what the gateway and the voice agent say about each one
        chat = next(r["chat_id"] for r in rows if r.get("client_message_id") == entry["client_message_id"])
        pending = (await gw.http.get(f"/v1/chats/{chat}/messages")).json().get("pending", [])
        entry["outgoing"] = [p for p in pending if p.get("client_message_id") == entry["client_message_id"]]
        for name in ("voice_agent.log", "gateway.log"):
            path = stack.data_dir / "logs" / name
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.exists() else []
            entry[name] = [line[:300] for line in lines if entry["client_message_id"] in line][:10]
    shown_twice = 0
    for text in integrity.get("repeated_user_message_texts", []):
        found = (await gw.http.get("/v1/search", params={"q": text})).json()["results"]
        if sum(1 for r in found if r["role"] == "user" and r["text"] == text) > 1:
            shown_twice += 1
    integrity["user_messages_shown_twice_in_chat"] = shown_twice
    return {
        "chats": chats,
        "seconds": seconds,
        "agent_restart": killed,
        **_load_summary(rows, series, seconds),
        **integrity,
    }


# ---- workload 6 --------------------------------------------------------------------------------------------------


def _synthetic_events(
    chat_ids: list[tuple[str, str]], first: int, count: int, rng: random.Random
) -> list[dict[str, Any]]:
    now = datetime.now(UTC).isoformat()
    events = []
    for i in range(first, first + count):
        project_id, chat_id = chat_ids[i % len(chat_ids)]
        words = " ".join(rng.choice(VOCABULARY) for _ in range(12))
        if i % 5000 == 0:
            words += f" {RARE_WORD}"
        user = i % 2 == 0
        payload = {"text": words, "client_message_id": f"hist-{i}"} if user else {"text": words}
        events.append(
            {
                "event_id": str(uuid.UUID(int=i + 1)),
                "schema_version": 1,
                "source": "collector",
                "seq": i + 1,
                "ts": now,
                "project_id": project_id,
                "chat_id": chat_id,
                "type": "user_message" if user else "assistant_message",
                "payload": payload,
            }
        )
    return events


def _folder_bytes(path: pathlib.Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


async def _timed(gw: Gateway, path: str, params: dict[str, Any], repeats: int = 20) -> dict[str, float]:
    times = []
    for _ in range(repeats):
        start = time.perf_counter()
        response = await gw.http.get(path, params=params)
        response.raise_for_status()
        times.append((time.perf_counter() - start) * 1000)
    return summary(times)


async def history(gw: Gateway, stack: Stack, sizes: tuple[int, ...] = (1_000, 10_000, 100_000)) -> dict[str, Any]:
    """Workload 6: read speed and disk use as the stored history grows. Events go in through the ingest API."""
    rng = random.Random(20261029)  # noqa: S311
    chats = []
    for i in range(10):
        chat = await gw.new_chat(f"history-{i}")
        chats.append((gw.project_id, chat))
    token = stack.token
    gateway_dir = stack.data_dir / "services" / "gateway"
    result: dict[str, Any] = {}
    stored = 0
    base_bytes = _folder_bytes(gateway_dir)
    last_bytes, last_count = base_bytes, 0
    async with httpx.AsyncClient(base_url=GATEWAY, timeout=60) as ingest:
        for size in sizes:
            started = time.perf_counter()
            while stored < size:
                batch = _synthetic_events(chats, stored, min(500, size - stored), rng)
                response = await ingest.post(
                    "/v1/events", json={"events": batch}, headers={"Authorization": f"Bearer {token}"}
                )
                response.raise_for_status()
                stored += len(batch)
            ingest_seconds = time.perf_counter() - started
            await asyncio.sleep(1)
            bytes_now = _folder_bytes(gateway_dir)
            chat_id = chats[0][1]
            newest = (await gw.http.get(f"/v1/chats/{chat_id}/messages", params={"limit": 50})).json()["messages"]
            middle = newest[len(newest) // 2]["pos"] - (size // 20) if newest else 0
            result[f"events_{size}"] = {
                "ingest_events_per_second": round((size - last_count) / ingest_seconds, 1),
                "gateway_disk_mb": round(bytes_now / 1_048_576, 2),
                "disk_bytes_per_1000_events": round((bytes_now - last_bytes) / (size - last_count) * 1000),
                "page_latest_50_ms": await _timed(gw, f"/v1/chats/{chat_id}/messages", {"limit": 50}),
                "page_older_50_ms": await _timed(
                    gw, f"/v1/chats/{chat_id}/messages", {"limit": 50, "before": max(middle, 1)}
                ),
                "search_common_word_ms": await _timed(gw, "/v1/search", {"q": VOCABULARY[7]}),
                "search_rare_word_ms": await _timed(gw, "/v1/search", {"q": RARE_WORD}),
                "timeline_200_ms": await _timed(gw, f"/v1/chats/{chat_id}/timeline", {"after": 0, "limit": 200}),
            }
            last_bytes, last_count = bytes_now, size
    return result


WORKLOADS = {
    "serial": serial_chat,
    "burst": burst,
    "many": many_chats,
    "history": history,
    "soak": soak,
}
