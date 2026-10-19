"""How long this service keeps working data, and the hourly clean-up that enforces it.

Working data here is the events already delivered to the gateway and the record of which messages were already
answered (kept so that a repeated message is not answered twice). What the agent remembers of a chat (the
transcript and its tasks) is not working data: it stays until the chat is deleted.

The gateway owns the setting and sends it here; this service keeps its own copy, so the clean-up is right even
while the gateway is down. 0 days means "keep until deleted by hand": nothing is pruned.
"""

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta

from thursday_voice_agent.application.ports import Outbox, SettingsRecords, TurnRecords

log = logging.getLogger(__name__)
SETTING = "retention"


class WorkingData:
    def __init__(self, settings: SettingsRecords, turns: TurnRecords, outbox: Outbox, default_days: int) -> None:
        self._settings = settings
        self._turns = turns
        self._outbox = outbox
        saved = settings.get_setting(SETTING)
        self._days = int(saved["days"]) if isinstance(saved, dict) and "days" in saved else default_days

    @property
    def days(self) -> int:
        return self._days

    def apply(self, days: int) -> int:
        """Take the period the gateway sent. The next clean-up uses it."""
        self._days = days
        self._settings.set_setting(SETTING, {"days": days})
        return days

    def prune(self) -> dict[str, int]:
        """Remove working data older than the period. Returns how many events and answered-turn records went."""
        if self._days <= 0:
            return {"events": 0, "turns": 0}
        age = timedelta(days=self._days)
        return {
            "events": self._outbox.prune_sent(age),
            "turns": self._turns.prune_turns(datetime.now(UTC) - age),
        }

    async def run(self, stop: asyncio.Event, every: float = 3600.0) -> None:
        while not stop.is_set():
            try:
                done = self.prune()
                if done["events"] or done["turns"]:
                    log.info("retention removed %d sent events and %d answered-turn records", *done.values())
            except Exception:
                log.exception("retention clean-up failed; it runs again later")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=every)
