from datetime import UTC, datetime

from thursday_contracts.task_control import PauseState
from thursday_main_agent.application.keep_awake import KeepAwake
from thursday_main_agent.domain.tasks import TaskPhase, TaskRecord


class Power:
    def __init__(self) -> None:
        self.calls: list[bool] = []

    def keep_awake(self, on: bool) -> None:
        self.calls.append(on)


def task(phase: TaskPhase, pause: PauseState = PauseState.NONE) -> TaskRecord:
    return TaskRecord("t1", "c1", "p1", "C:/x", "go", datetime.now(UTC), phase=phase, pause_state=pause)


def test_running_or_waiting_tasks_keep_the_pc_awake_and_release_after() -> None:
    tasks: list[TaskRecord] = [task(TaskPhase.INPUT_REQUIRED)]
    power = Power()
    guard = KeepAwake(lambda: tasks, power, paused_hold_seconds=60)
    assert guard.update() and power.calls == [True]
    guard.update()
    assert power.calls == [True], "only changes are sent"
    tasks.clear()
    assert not guard.update() and power.calls == [True, False]


def test_a_paused_task_holds_only_for_the_limit() -> None:
    now = [0.0]
    tasks = [task(TaskPhase.WORKING, PauseState.PAUSED)]
    guard = KeepAwake(lambda: tasks, Power(), paused_hold_seconds=1800, clock=lambda: now[0])
    assert guard.needed()
    now[0] = 1799
    assert guard.needed()
    now[0] = 1801
    assert not guard.needed()
