"""Behaviour settings the owner can change while the service runs: when to compact, how long a paused task
keeps the PC awake. Saved, and applied at once."""

from pydantic import BaseModel, Field

from thursday_main_agent.application.keep_awake import KeepAwake
from thursday_main_agent.application.ports import SettingsRecords
from thursday_main_agent.application.runner import TaskRunner

SETTING = "behavior"


class Behavior(BaseModel):
    compaction_threshold_percent: float = Field(ge=10, le=99)
    keep_awake_paused_minutes: float = Field(ge=0, le=24 * 60)


class BehaviorSettings:
    def __init__(self, settings: SettingsRecords, keep_awake: KeepAwake, defaults: Behavior) -> None:
        self._settings = settings
        self._keep_awake = keep_awake
        self._runner: TaskRunner | None = None
        self._now = Behavior.model_validate({**defaults.model_dump(), **(settings.get_setting(SETTING) or {})})
        keep_awake.paused_hold_seconds = self._now.keep_awake_paused_minutes * 60

    def attach(self, runner: TaskRunner) -> None:
        """The loop exists only once the service has started."""
        self._runner = runner

    def current(self) -> Behavior:
        return self._now

    def apply(self, new: Behavior) -> None:
        self._now = new
        self._settings.set_setting(SETTING, new.model_dump())
        self._keep_awake.paused_hold_seconds = new.keep_awake_paused_minutes * 60
        if self._runner is not None:
            self._runner.compaction_threshold_percent = new.compaction_threshold_percent
