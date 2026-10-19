"""How long things are kept: the setting, the hourly clean-up of the gateway's own data, and passing it on.

Two periods, both in days:
- `data_retention_days`: working data. Here that is the agents' stored events (timeline steps and traces). The
  gateway owns this setting for the whole system: it sends it to each agent, which applies it to its own working
  data and keeps its own copy. 0 keeps working data until it is deleted by hand.
- `metrics_retention_days`: the Monitor's history.

Projects, chats, messages and the task list are never removed by age: they go only when they are deleted.
"""

import asyncio
import logging
import time
from collections.abc import Mapping
from datetime import timedelta

from thursday_gateway.application.errors import AgentRefused, AgentUnavailable
from thursday_gateway.application.ports import EventLog, MetricsHistory, RetentionTarget, SettingsRecords
from thursday_gateway.application.waiting import wait_any

log = logging.getLogger(__name__)
SETTING = "retention"
DATA = "data_retention_days"
METRICS = "metrics_retention_days"
OLD_DATA = "trace_retention_days"  # what `data_retention_days` was called while it covered only traces


class Retention:
    def __init__(
        self,
        settings: SettingsRecords,
        events: EventLog,
        metrics: MetricsHistory | None,
        defaults: dict[str, int],
        targets: Mapping[str, RetentionTarget] | None = None,
    ) -> None:
        self._settings = settings
        self._events = events
        self._metrics = metrics
        self._defaults = defaults
        self._targets = dict(targets or {})
        self._told: dict[str, int] = {}  # the period each service last confirmed
        self.wakeup = asyncio.Event()

    def current(self) -> dict[str, int]:
        """The periods in force: what was saved from Settings, over the values from `.env`."""
        saved = dict(self._settings.get_setting(SETTING) or {})
        if DATA not in saved and OLD_DATA in saved:
            saved[DATA] = saved[OLD_DATA]
        return {key: int(saved.get(key, self._defaults[key])) for key in (DATA, METRICS)}

    def change(self, patch: Mapping[str, int]) -> dict[str, int]:
        merged = {**self.current(), **{key: patch[key] for key in (DATA, METRICS) if key in patch}}
        self._settings.set_setting(SETTING, merged)
        self.wakeup.set()  # the loop tells the other services without waiting for its next pass
        return merged

    def remove_orphans(self) -> int:
        """Rows that belong to chats or projects that no longer exist (left by earlier versions)."""
        return self._events.purge_orphans()

    def prune(self) -> int:
        """Delete what is older than its period. Returns how many events went."""
        days = self.current()
        removed = self._events.prune_events(timedelta(days=days[DATA])) if days[DATA] > 0 else 0
        if self._metrics is not None:
            self._metrics.prune(timedelta(days=days[METRICS]))
        return removed

    async def sync(self) -> list[str]:
        """Tell each service the working-data period, unless it already confirmed this one. A service that is
        down is told on a later pass. Returns the services told now."""
        days = self.current()[DATA]
        told = []
        for name, target in self._targets.items():
            if self._told.get(name) == days:
                continue
            try:
                await target.set_retention(days)
            except (AgentUnavailable, AgentRefused) as exc:
                log.info("the %s has not taken the retention period yet: %s", name, exc)
                continue
            self._told[name] = days
            told.append(name)
        return told

    async def run(self, stop: asyncio.Event, prune_every: float = 3600.0, sync_every: float = 60.0) -> None:
        next_prune = 0.0
        while not stop.is_set():
            await self.sync()
            if time.monotonic() >= next_prune:
                next_prune = time.monotonic() + prune_every
                removed = self.prune()
                if removed:
                    log.info("retention removed %d old events", removed)
            self.wakeup.clear()
            await wait_any(stop, self.wakeup, timeout=sync_every)
