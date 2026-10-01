"""Metrics history: a sample every few seconds for 24 hours, one per minute for the retention period.

Samples may arrive every second for the live Monitor; only the newest is kept in memory, and history is
written at most every RAW_EVERY, which keeps the database small.
"""

import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from thursday_contracts.metrics import MetricsSample

RAW_KEEP = timedelta(hours=24)
RAW_EVERY = timedelta(seconds=5)


class MetricsStore:
    def __init__(self, path: Path) -> None:
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self._db.execute("pragma journal_mode=wal")
        self._db.execute("create table if not exists raw (ts text primary key, sample text not null)")
        self._db.execute("create table if not exists minute (minute text primary key, sample text not null)")
        self._latest: dict[str, Any] | None = None
        self._last_raw: datetime | None = None

    def add(self, sample: MetricsSample) -> None:
        body = sample.model_dump_json()
        ts = sample.ts.astimezone(UTC)
        with self._lock:
            self._latest = json.loads(body)
            if self._last_raw is not None and timedelta(0) <= ts - self._last_raw < RAW_EVERY:
                return
            self._last_raw = ts
            self._db.execute("insert or replace into raw values (?, ?)", (ts.isoformat(), body))
            self._db.execute(
                "insert or replace into minute values (?, ?)", (ts.replace(second=0, microsecond=0).isoformat(), body)
            )

    def latest(self) -> dict[str, Any] | None:
        with self._lock:
            if self._latest is not None:
                return self._latest
            row = self._db.execute("select sample from raw order by ts desc limit 1").fetchone()
        return json.loads(row[0]) if row else None

    def history(self, span: timedelta, max_points: int = 720) -> list[dict[str, Any]]:
        since = (datetime.now(UTC) - span).isoformat()
        table, key = ("raw", "ts") if span <= timedelta(hours=1) else ("minute", "minute")
        with self._lock:
            rows = self._db.execute(
                f"select sample from {table} where {key} >= ? order by {key}",  # noqa: S608 - fixed names
                (since,),
            ).fetchall()
        step = max(1, len(rows) // max_points)
        return [json.loads(r[0]) for r in rows[::step]]

    def prune(self, keep: timedelta) -> None:
        now = datetime.now(UTC)
        with self._lock:
            self._db.execute("delete from raw where ts < ?", ((now - RAW_KEEP).isoformat(),))
            self._db.execute("delete from minute where minute < ?", ((now - keep).isoformat(),))

    def close(self) -> None:
        with self._lock:
            self._db.close()
