"""How long this service keeps working data, and the hourly clean-up that enforces it.

Working data is what was kept about how a task was done: the events already delivered to the gateway, and for
a finished task its saved steps, its record in the task protocol, its run-once marks and its answered approvals.
What the agent remembers of a chat (the transcript, the task list, its summaries) is not working data: it stays
until the chat is deleted.

The gateway owns the setting and sends it here; this service keeps its own copy, so the clean-up is right even
while the gateway is down. 0 days means "keep until deleted by hand": nothing is pruned.
"""

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta

from thursday_main_agent.application.ports import Outbox, SettingsRecords, TaskProtocolRecords, WorkingDataRecords
from thursday_main_agent.application.runner import TaskRunner

log = logging.getLogger(__name__)
SETTING = "retention"


class WorkingData:
    def __init__(
        self, settings: SettingsRecords, records: WorkingDataRecords, outbox: Outbox, default_days: int
    ) -> None:
        self._settings = settings
        self._records = records
        self._outbox = outbox
        saved = settings.get_setting(SETTING)
        self._days = int(saved["days"]) if isinstance(saved, dict) and "days" in saved else default_days
        self._runner: TaskRunner | None = None
        self._protocol: TaskProtocolRecords | None = None

    def attach(self, runner: TaskRunner, protocol: TaskProtocolRecords) -> None:
        """The loop's saved steps and the task protocol's records exist only once the service has started."""
        self._runner = runner
        self._protocol = protocol

    @property
    def days(self) -> int:
        return self._days

    def apply(self, days: int) -> int:
        """Take the period the gateway sent. The next clean-up uses it."""
        self._days = days
        self._settings.set_setting(SETTING, {"days": days})
        return days

    async def prune(self) -> dict[str, int]:
        """Remove working data older than the period. Returns how many events and tasks were cleaned."""
        if self._days <= 0:
            return {"events": 0, "tasks": 0}
        age = timedelta(days=self._days)
        events = self._outbox.prune_sent(age)
        tasks = 0
        if self._runner is not None and self._protocol is not None:
            for task_id in self._records.ended_uncleared(datetime.now(UTC) - age):
                await self._runner.forget(task_id)
                await self._protocol.forget(task_id)
                self._records.clear_working_data(task_id)
                tasks += 1
        return {"events": events, "tasks": tasks}

    async def run(self, stop: asyncio.Event, every: float = 3600.0) -> None:
        while not stop.is_set():
            try:
                done = await self.prune()
                if done["events"] or done["tasks"]:
                    log.info("retention removed %d sent events and the working data of %d tasks", *done.values())
            except Exception:
                log.exception("retention clean-up failed; it runs again later")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=every)
