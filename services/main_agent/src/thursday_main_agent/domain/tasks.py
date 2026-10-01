"""The main agent's own record of a task, beside the A2A task the SDK stores.

Pause takes effect at the next step boundary (a step is one LLM call plus its tool calls).
A paused task stays A2A `WORKING` with `pause_state` metadata.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from thursday_contracts.task_control import PauseState


class TaskPhase(StrEnum):
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


TERMINAL_PHASES = frozenset({TaskPhase.COMPLETED, TaskPhase.FAILED, TaskPhase.CANCELED})


class TaskNotControllable(Exception):
    pass


@dataclass(slots=True)
class TaskRecord:
    task_id: str
    chat_id: str
    project_id: str
    project_folder: str
    instruction: str
    created_at: datetime
    phase: TaskPhase = TaskPhase.SUBMITTED
    pause_state: PauseState = PauseState.NONE
    timeout_streak: int = 0
    history_len: int = 0
    transcript_saved: bool = False

    @property
    def terminal(self) -> bool:
        return self.phase in TERMINAL_PHASES

    def request_pause(self) -> PauseState:
        if self.terminal:
            raise TaskNotControllable(f"task {self.task_id} is {self.phase}")
        if self.pause_state is PauseState.NONE:
            self.pause_state = PauseState.PAUSING
        return self.pause_state

    def reach_step_boundary(self) -> bool:
        """True when a requested pause takes effect now."""
        if self.pause_state is PauseState.PAUSING:
            self.pause_state = PauseState.PAUSED
            return True
        return self.pause_state is PauseState.PAUSED

    def request_resume(self) -> bool:
        """True when the task was paused and must be woken; a pending pause is just withdrawn."""
        if self.terminal:
            raise TaskNotControllable(f"task {self.task_id} is {self.phase}")
        was_paused = self.pause_state is PauseState.PAUSED
        self.pause_state = PauseState.NONE
        return was_paused

    def auto_pause(self) -> None:
        if not self.terminal:
            self.pause_state = PauseState.PAUSING
