"""One task per request name, no task in a deleted chat, and no change to the model while it answers.

Real SDK, real ingress guard and real SQLite stores, over A2A as the voice agent calls it; only the model is
scripted.
"""

import asyncio
import shutil
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from langchain_core.messages import AIMessage, BaseMessage
from thursday_main_agent.domain.tasks import DuplicateRequest, TaskRecord
from thursday_main_agent.infrastructure.store import Store

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" and shutil.which("pwsh") is None, reason="the shell tools need Windows or pwsh"
)


def answer_once(_messages: list[BaseMessage]) -> AIMessage:
    return AIMessage("Done as asked.")


def start_message(workspace: Path, text: str, request: str | None, chat_id: str = "chat-1") -> dict[str, Any]:
    metadata = {"thursday.project_id": "proj-1", "thursday.project_folder": str(workspace)}
    if request is not None:
        metadata["thursday.request"] = request
    return {
        "message": {
            "messageId": request or str(uuid.uuid4()),
            "role": "ROLE_USER",
            "contextId": chat_id,
            "parts": [{"text": text}],
            "metadata": metadata,
        },
        "configuration": {"returnImmediately": True},
    }


async def test_a_request_sent_again_gets_the_task_it_already_started(start, workspace) -> None:
    async with start(answer_once) as h:
        first = await h.rpc("SendMessage", start_message(workspace, "Tidy the logs", "request-1"))
        task_id = first["result"]["task"]["id"]
        await h.wait(task_id, "completed")
        calls = h.chat.calls

        again = await h.rpc("SendMessage", start_message(workspace, "Tidy the logs", "request-1"))
        assert again["result"]["task"]["id"] == task_id, "the same task, not a second one"
        assert again["result"]["task"]["status"]["state"] == "TASK_STATE_COMPLETED", "as it stands now"
        assert again["result"]["task"]["contextId"] == "chat-1"
        await asyncio.sleep(0.3)
        assert h.chat.calls == calls, "the work was not done again"
        assert len(await h.events("delegation")) == 1

        other = await h.rpc("SendMessage", start_message(workspace, "Tidy the logs", "request-2"))
        assert other["result"]["task"]["id"] != task_id, "another name is another request, even with the same words"
        unnamed = await h.rpc("SendMessage", start_message(workspace, "Tidy the logs", None))
        assert unnamed["result"]["task"]["id"] not in (task_id, other["result"]["task"]["id"])


async def test_a_request_is_still_known_after_a_restart(start, workspace) -> None:
    async with start(answer_once) as h:
        first = await h.rpc("SendMessage", start_message(workspace, "Tidy the logs", "request-1"))
        task_id = first["result"]["task"]["id"]
        await h.wait(task_id, "completed")
    async with start(answer_once) as h:
        again = await h.rpc("SendMessage", start_message(workspace, "Tidy the logs", "request-1"))
        assert again["result"]["task"]["id"] == task_id
        assert h.chat.calls == 0, "nothing ran in the restarted agent"


def test_two_tasks_cannot_be_recorded_under_one_request_name(tmp_path: Path) -> None:
    store = Store(tmp_path / "main_agent.sqlite")
    store.insert_task(TaskRecord("t1", "chat-1", "p1", "C:/w", "work", datetime.now(UTC)), "request-1")
    with pytest.raises(DuplicateRequest) as refused:
        store.insert_task(TaskRecord("t2", "chat-1", "p1", "C:/w", "work", datetime.now(UTC)), "request-1")
    assert refused.value.task_id == "t1" and store.get_task("t2") is None, "the second one left nothing behind"
    assert store.task_for_request("request-1") == "t1" and store.task_for_request("request-9") is None
    store.close()


async def test_no_task_starts_in_a_chat_that_was_deleted(start, workspace) -> None:
    async with start(answer_once) as h:
        task_id = await h.new_task("Tidy the logs")
        await h.wait(task_id, "completed")
        assert (await h.client.delete("/v1/chats/chat-1")).status_code == 200

        refused = await h.rpc("SendMessage", start_message(workspace, "And the old ones", "request-2"))
        assert refused["error"]["message"] == "this chat was deleted", refused
        calls = h.chat.calls
        await asyncio.sleep(0.3)
        assert h.chat.calls == calls and await h.events() == [], "nothing ran, and nothing is kept for the chat"

        elsewhere = await h.rpc("SendMessage", start_message(workspace, "Tidy the logs", "request-3", "chat-2"))
        assert "result" in elsewhere, "other chats are not affected"


def test_a_deleted_chat_is_not_written_back_by_work_that_was_still_ending(tmp_path: Path) -> None:
    store = Store(tmp_path / "main_agent.sqlite")
    task = TaskRecord("t1", "chat-1", "p1", "C:/w", "work", datetime.now(UTC))
    store.insert_task(task, "request-1")
    assert store.delete_chat("chat-1") == ["t1"]
    assert store.chat_deleted("chat-1") and not store.chat_deleted("chat-2")
    store.save_task(task)  # the task was winding down when its chat went
    store.append_transcript("chat-1", "t1", [{"type": "ai", "data": {"content": "late"}}])
    assert store.get_task("t1") is None and store.load_transcript("chat-1") == []
    assert store.task_for_request("request-1") is None, "the request's name went with the chat"
    store.close()


async def test_changing_the_model_while_it_answers_is_refused_with_the_reason(start) -> None:
    answering, finish = asyncio.Event(), asyncio.Event()

    def slow(_messages: list[BaseMessage]) -> AIMessage:
        return AIMessage("Done.")

    async with start(slow) as h:
        real = h.chat.astream

        async def held(messages: list[BaseMessage]) -> Any:
            answering.set()
            await finish.wait()
            async for part in real(messages):
                yield part

        h.chat.astream = held  # type: ignore[method-assign]
        task_id = await h.new_task("Tidy the logs")
        await asyncio.wait_for(answering.wait(), 10)

        saved = await h.client.put("/v1/llm", json={"inference": {"temperature": 0.2}})
        assert saved.status_code == 409 and "in use right now" in saved.json()["detail"]
        assert (await h.client.post("/v1/model/unload")).status_code == 409
        assert (await h.client.post("/v1/model/reload")).status_code == 409
        assert (await h.client.get("/v1/llm")).json()["inference"]["temperature"] != 0.2, "nothing was changed"

        finish.set()
        await h.wait(task_id, "completed")
        after = await h.client.put("/v1/llm", json={"inference": {"temperature": 0.2}})
        assert after.status_code == 200 and after.json()["inference"]["temperature"] == 0.2


async def test_a_chat_delete_that_failed_half_way_is_finished_by_asking_again(tmp_path: Path) -> None:
    from thursday_main_agent.application.deletion import Deletion

    store = Store(tmp_path / "main.sqlite")
    now = datetime.now(UTC)
    store.insert_task(TaskRecord("t1", "chat-1", "p1", str(tmp_path), "do it", now))

    class Steps:
        """The saved steps of the loop: removing them fails the first time."""

        def __init__(self) -> None:
            self.forgotten: list[str] = []
            self.fail = True

        async def forget(self, task_id: str) -> None:
            if self.fail:
                self.fail = False
                raise OSError("database is locked")
            self.forgotten.append(task_id)

    class Quiet:
        def forget(self, **_: object) -> int:
            return 0

        async def forget_chat(self, chat_id: str) -> None:
            return None

        async def forget_project(self, project_id: str) -> int:
            return 0

        async def stop_project(self, project_id: str) -> bool:
            return False

    steps, protocol, quiet = Steps(), Steps(), Quiet()
    protocol.fail = False
    deletion = Deletion(store, cast(Any, quiet), cast(Any, quiet), cast(Any, quiet))
    deletion.attach(cast(Any, steps), cast(Any, protocol))
    with pytest.raises(OSError):
        await deletion.chat("chat-1")
    assert store.chat_deleted("chat-1"), "nothing more starts in the chat from the first try on"
    assert await deletion.chat("chat-1") == 1, "the second try still knows the task"
    assert steps.forgotten == ["t1"] and protocol.forgotten == ["t1"]
    assert store.get_task("t1") is None
    assert await deletion.chat("chat-1") == 0, "and a third finds nothing left"
