"""Model errors never leave a task stuck, and tasks take turns on the one model."""

import json
import shutil
import sys
from collections.abc import Callable
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from thursday_main_agent.application.model_call import classify_error, reply_problem

Script = Callable[[list[BaseMessage]], AIMessage]
windows_only = pytest.mark.skipif(
    sys.platform != "win32" and shutil.which("pwsh") is None, reason="the shell tools need Windows or pwsh"
)


def call(name: str, args: dict[str, Any], n: int = 1) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": f"call-{n}"}])


def failing_first(error: Exception, times: int = 1, then: str = "all done") -> Script:
    """A model that raises `error` on its first `times` calls and then answers."""
    calls = {"n": 0}

    def script(messages: list[BaseMessage]) -> AIMessage:
        calls["n"] += 1
        if calls["n"] <= times:
            raise error
        return AIMessage(then)

    return script


# --- what counts as which kind of error ---------------------------------------------------------
def test_a_full_window_is_recognised_whatever_the_exception_type() -> None:
    assert classify_error(ValueError("500: Context size has been exceeded.")) == "context"
    assert classify_error(RuntimeError("the request is larger than the context length")) == "context"


def test_a_cut_off_tool_call_is_recognised() -> None:
    assert classify_error(json.JSONDecodeError("Unterminated string starting at", '{"path": "a', 9)) == "truncated"
    assert classify_error(ValueError("Invalid JSON: EOF while parsing a string at line 1 column 40")) == "truncated"


def test_other_errors_are_not_mistaken_for_either() -> None:
    assert classify_error(RuntimeError("boom")) is None
    assert classify_error(RuntimeError("Unterminated string")) is None, "only a JSON ValueError means a cut-off call"


def test_replies_that_end_a_turn_badly_are_caught() -> None:
    invalid = AIMessage("", invalid_tool_calls=[{"name": "fs_read", "args": '{"path": "a', "id": "1", "error": "x"}])
    incomplete = AIMessage("half an answ", response_metadata={"status": "incomplete"})
    problems = [reply_problem(invalid), reply_problem(incomplete), reply_problem(AIMessage("  "))]
    assert [p.kind for p in problems if p] == ["truncated", "truncated", "empty"]
    assert reply_problem(AIMessage("fine")) is None
    assert reply_problem(call("fs_read", {"path": "a"})) is None


# --- a failed model call is retried once, then the task fails clearly ---------------------------
@windows_only
async def test_a_window_overflow_mid_stream_is_retried_once_and_the_task_finishes(start) -> None:
    script = failing_first(ValueError("500: Context size has been exceeded."))
    async with start(script) as h:
        task = await h.wait(await h.new_task("Say hi"), "completed")
        assert task["artifacts"][0]["parts"][0]["text"] == "all done"
        statuses = [(e["payload"]["status"], e["payload"]["attempt"]) for e in await h.events("llm_call")]
        assert statuses == [("error: context", 1), ("ok", 2)], "the retry is numbered after the failed call"


@windows_only
async def test_a_cut_off_tool_call_is_retried_once_and_the_task_finishes(start) -> None:
    cut = json.JSONDecodeError("Unterminated string starting at", '{"path": "a', 9)
    async with start(failing_first(cut)) as h:
        await h.wait(await h.new_task("Say hi"), "completed")
        assert [e["payload"]["status"] for e in await h.events("llm_call")] == ["error: truncated", "ok"]


@windows_only
async def test_an_empty_reply_is_retried_once(start) -> None:
    calls = {"n": 0}

    def script(messages: list[BaseMessage]) -> AIMessage:
        calls["n"] += 1
        return AIMessage("") if calls["n"] == 1 else AIMessage("now an answer")

    async with start(script) as h:
        task = await h.wait(await h.new_task("Say hi"), "completed")
        assert task["artifacts"][0]["parts"][0]["text"] == "now an answer"


@windows_only
async def test_a_window_that_stays_full_fails_the_task_with_a_message_and_a_notification(start) -> None:
    async with start(failing_first(ValueError("500: Context size has been exceeded."), times=99)) as h:
        task = await h.wait(await h.new_task("Say hi"), "failed")
        message = task["status"]["message"]["parts"][0]["text"]
        assert "ran out of context window" in message and "larger context length" in message
        (note,) = await h.events("notification")
        assert note["payload"]["kind"] == "failed" and "ran out of context window" in note["payload"]["body"]
        assert len(await h.events("llm_call")) == 2, "retried once, not forever"


@windows_only
async def test_an_unexpected_model_error_fails_the_task_instead_of_leaving_it_working(start) -> None:
    async with start(failing_first(RuntimeError("the model exploded"), times=99)) as h:
        task = await h.wait(await h.new_task("Say hi"), "failed")
        assert "RuntimeError: the model exploded" in task["status"]["message"]["parts"][0]["text"]
        assert len(await h.events("llm_call")) == 1, "an unknown error is not retried"


@windows_only
async def test_a_bug_inside_the_agent_still_ends_the_task(start, monkeypatch: pytest.MonkeyPatch) -> None:
    from thursday_main_agent.application.runner import TaskRunner

    async def broken(self, state, config):
        raise RuntimeError("tool layer crashed")

    monkeypatch.setattr(TaskRunner, "_tools_node", broken)
    async with start(lambda m: call("fs_read", {"path": "old.log"})) as h:
        task = await h.wait(await h.new_task("Read old.log"), "failed")
        assert "unexpected error" in task["status"]["message"]["parts"][0]["text"]
        assert "tool layer crashed" in task["status"]["message"]["parts"][0]["text"]


# --- one task at a time on the model ------------------------------------------------------------
@windows_only
async def test_tasks_take_turns_on_the_model(start) -> None:
    order: list[str] = []

    def script(messages: list[BaseMessage]) -> AIMessage:
        asked = next(m.text for m in reversed(messages) if isinstance(m, HumanMessage))
        steps = sum(1 for m in messages if isinstance(m, AIMessage) and m.tool_calls)
        order.append(f"{asked}:{steps}")
        return call("fs_read", {"path": "old.log"}, n=steps + 1) if steps < 2 else AIMessage(f"{asked} done")

    async with start(script) as h:
        first = await h.new_task("first", chat_id="chat-a")
        second = await h.new_task("second", chat_id="chat-b")
        await h.wait(first, "completed")
        await h.wait(second, "completed")
        assert order == ["first:0", "first:1", "first:2", "second:0", "second:1", "second:2"], order
        queued = [e for e in await h.events("task_state") if e["payload"].get("queued")]
        assert [e["task_id"] for e in queued] == [second]
        assert queued[0]["payload"]["state"] == "submitted"
