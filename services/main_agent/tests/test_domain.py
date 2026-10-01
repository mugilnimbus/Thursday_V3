from datetime import UTC, datetime, timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from thursday_contracts.approvals import ApprovalDecision
from thursday_contracts.task_control import PauseState
from thursday_main_agent.application.runner import CANCELED_RESULT, close_dangling_tool_calls
from thursday_main_agent.domain.approvals import Approval, ApprovalAlreadyResolved, ApprovalStatus, TimeoutStreak
from thursday_main_agent.domain.tasks import TaskNotControllable, TaskPhase, TaskRecord
from thursday_main_agent.domain.tool_calls import ToolNameMap, call_key

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def approval() -> Approval:
    return Approval.open("ap-1", "t1", "c1", "t1:1:0", "shell", "Run x", {}, NOW, timedelta(seconds=300))


def test_first_answer_wins() -> None:
    a = approval()
    a.answer(ApprovalDecision.ALLOW_ONCE, "gateway", NOW)
    with pytest.raises(ApprovalAlreadyResolved):
        a.answer(ApprovalDecision.DENY, "voice", NOW)
    assert a.status is ApprovalStatus.ALLOWED and a.resolved_by == "gateway" and a.mcp_action == "accept"


def test_late_answer_after_expiry_is_rejected_and_times_out() -> None:
    a = approval()
    with pytest.raises(ApprovalAlreadyResolved):
        a.answer(ApprovalDecision.ALLOW_ONCE, "gateway", NOW + timedelta(seconds=301))
    assert a.status is ApprovalStatus.TIMED_OUT and a.mcp_action == "cancel"


def test_deny_maps_to_decline_and_cancel_to_cancel() -> None:
    a = approval()
    a.answer(ApprovalDecision.DENY, "gateway", NOW)
    assert a.mcp_action == "decline"
    b = approval()
    b.cancel()
    assert b.mcp_action == "cancel"


def test_two_timeouts_in_a_row_pause_and_a_human_answer_resets() -> None:
    streak = TimeoutStreak(limit=2)
    assert not streak.record(ApprovalStatus.TIMED_OUT)
    assert not streak.record(ApprovalStatus.ALLOWED)
    assert not streak.record(ApprovalStatus.TIMED_OUT)
    assert streak.record(ApprovalStatus.TIMED_OUT)


def task(**kw: object) -> TaskRecord:
    return TaskRecord("t1", "c1", "p1", "C:/x", "do it", NOW, **kw)  # type: ignore[arg-type]


def test_pause_lands_at_the_step_boundary_and_resume_wakes_it() -> None:
    t = task(phase=TaskPhase.WORKING)
    assert t.request_pause() is PauseState.PAUSING
    assert t.request_pause() is PauseState.PAUSING  # repeatable
    assert t.reach_step_boundary() and t.pause_state is PauseState.PAUSED
    assert t.request_resume() is True and t.pause_state is PauseState.NONE


def test_resume_before_the_boundary_just_withdraws_the_pause() -> None:
    t = task(phase=TaskPhase.WORKING)
    t.request_pause()
    assert t.request_resume() is False and not t.reach_step_boundary()


@pytest.mark.parametrize("phase", [TaskPhase.COMPLETED, TaskPhase.FAILED, TaskPhase.CANCELED])
def test_finished_tasks_cannot_be_paused_or_resumed(phase: TaskPhase) -> None:
    with pytest.raises(TaskNotControllable):
        task(phase=phase).request_pause()
    with pytest.raises(TaskNotControllable):
        task(phase=phase).request_resume()


def test_tool_name_map_is_a_bijection_even_with_collisions() -> None:
    names = ToolNameMap(["fs.read", "fs_read", "shell.session.exec"])
    assert names.to_llm("fs.read") != names.to_llm("fs_read")
    for mcp_name in ("fs.read", "fs_read", "shell.session.exec"):
        assert names.to_mcp(names.to_llm(mcp_name)) == mcp_name
    assert names.to_mcp("nope") is None


def test_call_keys_are_ours() -> None:
    assert call_key("task-9", 3, 1) == "task-9:3:1"


def test_dangling_tool_calls_get_a_canceled_result() -> None:
    ai = AIMessage("", tool_calls=[{"name": "a", "args": {}, "id": "x"}, {"name": "b", "args": {}, "id": "y"}])
    closed = close_dangling_tool_calls([HumanMessage("go"), ai, ToolMessage("done", tool_call_id="x")])
    results = {m.tool_call_id: m.content for m in closed if isinstance(m, ToolMessage)}
    assert results == {"x": "done", "y": CANCELED_RESULT}
