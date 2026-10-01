"""Approval, pause, stop, and restart behavior of the main agent, end to end over A2A.

Real SDK, real ingress guard, real SQLite stores, real tool-server child process; only the
model is scripted. Real-model behavior is evaluated separately.
"""

import sys

import pytest
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="tool server targets Windows")


def results(messages: list[BaseMessage]) -> list[ToolMessage]:
    # Only this task's results: the seeded chat history ends at the last human message.
    last_human = max(i for i, m in enumerate(messages) if m.type == "human")
    return [m for m in messages[last_human:] if isinstance(m, ToolMessage)]


def delete_once(messages: list[BaseMessage]) -> AIMessage:
    done = results(messages)
    if not done:
        return AIMessage("", tool_calls=[{"name": "fs_delete", "args": {"path": "old.log"}, "id": "call-1"}])
    return AIMessage(f"Result: {done[-1].content}")


def keep_trying_delete(messages: list[BaseMessage]) -> AIMessage:
    done = results(messages)
    if len(done) < 3:
        return AIMessage("", tool_calls=[{"name": "fs_delete", "args": {"path": "old.log"}, "id": f"call-{len(done)}"}])
    return AIMessage(f"Gave up: {done[-1].content}")


async def test_allow_once_runs_the_call_and_second_answer_is_rejected(start, workspace) -> None:
    async with start(delete_once) as h:
        task_id = await h.new_task("Delete old.log")
        waiting = await h.wait(task_id, "input_required")
        approval = h.approval_of(waiting)
        assert approval["tool"] == "fs.delete" and "old.log" in approval["summary"]
        assert (workspace / "old.log").exists(), "nothing may run before approval"
        assert "result" in await h.answer(task_id, approval["approval_id"], "allow_once")
        done = await h.wait(task_id, "completed")
        assert not (workspace / "old.log").exists()
        assert "deleted file old.log" in done["artifacts"][0]["parts"][0]["text"]
        late = await h.answer(task_id, approval["approval_id"], "deny")
        assert late["error"]["code"] in (-32041, -32004)
        types = [e["type"] for e in await h.events()]
        for expected in (
            "delegation",
            "approval_requested",
            "approval_resolved",
            "tool_call",
            "llm_call",
            "notification",
        ):
            assert expected in types
        seqs = [e["seq"] for e in await h.events()]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


async def test_deny_does_not_run_and_the_model_is_told(start, workspace) -> None:
    async with start(delete_once) as h:
        task_id = await h.new_task("Delete old.log")
        approval = h.approval_of(await h.wait(task_id, "input_required"))
        await h.answer(task_id, approval["approval_id"], "deny")
        done = await h.wait(task_id, "completed")
    assert (workspace / "old.log").exists()
    assert "denied" in done["artifacts"][0]["parts"][0]["text"]


async def test_two_timeouts_in_a_row_pause_the_task_then_resume_finishes(start, workspace) -> None:
    async with start(keep_trying_delete, approval_seconds=1) as h:
        task_id = await h.new_task("Delete old.log")
        paused = await h.wait(task_id, "working", paused=True, timeout=30)
        assert paused["metadata"]["pause_state"] == "paused"
        notes = [e["payload"] for e in await h.events("notification")]
        assert any(n["kind"] == "auto_pause" for n in notes)
        resolved = [e["payload"]["outcome"] for e in await h.events("approval_resolved")]
        assert resolved.count("timed_out") == 2
        assert (await h.control("ResumeTask", task_id))["result"]["pause_state"] == "none"
        third = h.approval_of(await h.wait(task_id, "input_required"))
        await h.answer(task_id, third["approval_id"], "deny")
        await h.wait(task_id, "completed")
    assert (workspace / "old.log").exists()


async def test_pause_requested_while_waiting_lands_after_the_step(start) -> None:
    async with start(delete_once) as h:
        task_id = await h.new_task("Delete old.log")
        approval = h.approval_of(await h.wait(task_id, "input_required"))
        assert (await h.control("PauseTask", task_id))["result"]["pause_state"] == "pausing"
        assert (await h.control("PauseTask", task_id))["result"]["pause_state"] == "pausing"  # repeatable
        await h.answer(task_id, approval["approval_id"], "allow_once")
        await h.wait(task_id, "working", paused=True)
        calls_while_paused = h.chat.calls
        await h.control("ResumeTask", task_id)
        await h.wait(task_id, "completed")
        assert h.chat.calls == calls_while_paused + 1
        finished = await h.control("PauseTask", task_id)
        assert finished["error"]["code"] == -32040


async def test_stop_while_waiting_cancels_and_closes_the_transcript(start, workspace) -> None:
    async with start(delete_once) as h:
        task_id = await h.new_task("Delete old.log")
        approval = h.approval_of(await h.wait(task_id, "input_required"))
        canceled = await h.rpc("CancelTask", {"id": task_id})
        assert canceled["result"]["status"]["state"] == "TASK_STATE_CANCELED"
        late = await h.answer(task_id, approval["approval_id"], "allow_once")
        assert "error" in late
        outcomes = [e["payload"]["outcome"] for e in await h.events("approval_resolved")]
        assert outcomes == ["canceled"]
    assert (workspace / "old.log").exists()


async def test_restart_while_waiting_then_answer_finishes_the_task(start, workspace) -> None:
    async with start(delete_once) as h:
        task_id = await h.new_task("Delete old.log")
        approval = h.approval_of(await h.wait(task_id, "input_required"))
    async with start(delete_once) as h:
        assert (await h.get(task_id))["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
        await h.answer(task_id, approval["approval_id"], "allow_once")
        await h.wait(task_id, "completed")
    assert not (workspace / "old.log").exists()


async def test_allow_always_answers_repeat_requests_in_that_chat_only(start, workspace) -> None:
    async with start(delete_once) as h:
        first = await h.new_task("Delete old.log")
        approval = h.approval_of(await h.wait(first, "input_required"))
        await h.answer(first, approval["approval_id"], "allow_always")
        await h.wait(first, "completed")
        rules = (await h.client.get("/v1/chats/chat-1/allow-rules")).json()["rules"]
        assert [r["tool"] for r in rules] == ["fs.delete"]
        (workspace / "old.log").write_text("again", encoding="utf-8")
        second = await h.new_task("Delete old.log again")
        await h.wait(second, "completed")
        assert not (workspace / "old.log").exists()
        (workspace / "old.log").write_text("other chat", encoding="utf-8")
        other = await h.new_task("Delete old.log", chat_id="chat-2")
        await h.wait(other, "input_required")
        assert (await h.client.delete("/v1/chats/chat-1/allow-rules/fs.delete")).status_code == 204
        assert (await h.client.get("/v1/chats/chat-1/allow-rules")).json()["rules"] == []


async def test_next_task_in_the_chat_sees_the_previous_transcript(start) -> None:
    seen: list[int] = []

    def remember(messages: list[BaseMessage]) -> AIMessage:
        seen.append(sum(1 for m in messages if m.type == "human"))
        return AIMessage("ok")

    async with start(remember) as h:
        await h.wait(await h.new_task("first"), "completed")
        await h.wait(await h.new_task("second"), "completed")
    assert seen == [1, 2]


async def test_ingress_guard_refusals(start, workspace) -> None:
    async with start(delete_once) as h:
        task_id = await h.new_task("Delete old.log")
        await h.wait(task_id, "input_required")
        extra = await h.rpc(
            "SendMessage",
            {
                "message": {
                    "messageId": "m",
                    "role": "ROLE_USER",
                    "taskId": task_id,
                    "contextId": "chat-1",
                    "parts": [{"text": "also do X"}],
                }
            },
        )
        assert extra["error"]["code"] == -32004
        forged = await h.rpc(
            "SendMessage",
            {
                "message": {
                    "messageId": "m2",
                    "role": "ROLE_USER",
                    "taskId": task_id,
                    "contextId": "chat-1",
                    "parts": [{"data": {"kind": "thursday.internal", "action": "recover"}}],
                }
            },
        )
        assert forged["error"]["code"] == -32602
        no_meta = await h.rpc(
            "SendMessage",
            {"message": {"messageId": "m3", "role": "ROLE_USER", "contextId": "c", "parts": [{"text": "hi"}]}},
        )
        assert no_meta["error"]["code"] == -32602
        no_ext = await h.rpc("PauseTask", {"id": task_id})
        assert no_ext["error"]["code"] == -32601
        anonymous = await h.client.post(
            "/a2a",
            json={"jsonrpc": "2.0", "id": 1, "method": "GetTask", "params": {"id": task_id}},
            headers={"Authorization": "Bearer x"},
        )
        assert anonymous.status_code == 401


def slow_shell(messages: list[BaseMessage]) -> AIMessage:
    done = results(messages)
    if not done:
        return AIMessage("", tool_calls=[{"name": "shell", "args": {"command": "Start-Sleep -Seconds 30"}, "id": "c"}])
    return AIMessage(f"After restart: {done[-1].content}")


async def test_crash_during_a_tool_call_reports_outcome_unknown_and_never_reruns(start) -> None:
    import asyncio

    async with start(slow_shell) as h:
        task_id = await h.new_task("Wait a bit")
        approval = h.approval_of(await h.wait(task_id, "input_required"))
        await h.answer(task_id, approval["approval_id"], "allow_once")
        for _ in range(100):
            if any(e["payload"].get("status") == "running" for e in await h.events("tool_call")):
                break
            await asyncio.sleep(0.1)
        await asyncio.sleep(1)
    async with start(slow_shell) as h:
        done = await h.wait(task_id, "completed", timeout=60)
        text = done["artifacts"][0]["parts"][0]["text"]
        assert "Outcome unknown" in text
        statuses = [e["payload"]["status"] for e in await h.events("tool_call")]
        assert statuses == ["requested", "running", "unknown"], "the interrupted call must not run again"
