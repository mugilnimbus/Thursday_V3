"""Keep the PC awake while work is running or waiting for the user.

Running and approval-waiting tasks hold it; a paused task holds it only for a limited time.
It cannot prevent a manual sleep or a lid close.
"""

import asyncio
import contextlib
import time
from collections.abc import Callable
from typing import Protocol

from thursday_contracts.task_control import PauseState

from thursday_main_agent.domain.tasks import TaskPhase, TaskRecord


class Power(Protocol):
    def keep_awake(self, on: bool) -> None: ...


class KeepAwake:
    def __init__(
        self,
        open_tasks: Callable[[], list[TaskRecord]],
        power: Power,
        paused_hold_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._open_tasks = open_tasks
        self._power = power
        self.paused_hold_seconds = paused_hold_seconds
        self._clock = clock
        self._paused_since: dict[str, float] = {}
        self.active = False

    def needed(self) -> bool:
        now = self._clock()
        needed = False
        seen: set[str] = set()
        for task in self._open_tasks():
            if task.phase not in (TaskPhase.SUBMITTED, TaskPhase.WORKING, TaskPhase.INPUT_REQUIRED):
                continue
            if task.pause_state is PauseState.PAUSED:
                seen.add(task.task_id)
                since = self._paused_since.setdefault(task.task_id, now)
                needed = needed or now - since < self.paused_hold_seconds
            else:
                needed = True
        self._paused_since = {k: v for k, v in self._paused_since.items() if k in seen}
        return needed

    def update(self) -> bool:
        wanted = self.needed()
        if wanted != self.active:
            self._power.keep_awake(wanted)
            self.active = wanted
        return wanted

    async def run(self, stop: asyncio.Event, interval: float = 15.0) -> None:
        try:
            while not stop.is_set():
                self.update()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=interval)
        finally:
            if self.active:
                self._power.keep_awake(False)
                self.active = False
