"""Working data is kept for a chosen time, and a deleted chat leaves nothing in the tool server's call log."""

import asyncio
import shutil
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

windows_only = pytest.mark.skipif(
    sys.platform != "win32" and shutil.which("pwsh") is None, reason="the shell tools need Windows or pwsh"
)


def read_once(messages: list[BaseMessage]) -> AIMessage:
    """Read one file, then finish."""
    if isinstance(messages[-1], ToolMessage):
        return AIMessage("done")
    return AIMessage("", tool_calls=[{"name": "fs_read", "args": {"path": "old.log"}, "id": "call-1"}])


def rows(path: Path, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    db = sqlite3.connect(path)
    try:
        return db.execute(sql, params).fetchall()
    finally:
        db.close()


def run(path: Path, sql: str, params: tuple[Any, ...] = ()) -> None:
    db = sqlite3.connect(path, isolation_level=None)
    try:
        db.execute(sql, params)
    finally:
        db.close()


async def test_the_period_comes_from_the_gateway_is_kept_and_is_checked(start) -> None:
    async with start(lambda m: AIMessage("hi")) as h:
        assert (await h.client.get("/v1/retention")).json() == {"days": 30}, "the value from .env until one is sent"
        assert (await h.client.put("/v1/retention", json={"days": 90})).json() == {"days": 90}
        assert (await h.client.put("/v1/retention", json={"days": 90})).json() == {"days": 90}, "repeating is fine"
        assert (await h.client.put("/v1/retention", json={"days": -1})).status_code == 422
        assert (await h.client.put("/v1/retention", json={"days": 0})).json() == {"days": 0}, "0: until deleted"
    async with start(lambda m: AIMessage("hi")) as h:
        assert (await h.client.get("/v1/retention")).json() == {"days": 0}, "this service keeps its own copy"


@windows_only
async def test_a_finished_tasks_working_data_goes_after_the_period_and_the_chat_stays(start) -> None:
    async with start(read_once) as h:
        task_id = await h.new_task("Read old.log")
        await h.wait(task_id, "completed")
        data = h.data_dir
        assert rows(data / "main_agent.sqlite", "select count(*) from call_marks")[0][0] == 1
        assert rows(data / "checkpoints.sqlite", "select count(*) from checkpoints where thread_id = ?", (task_id,))[0][
            0
        ]
    # Thirty-one days later: the task ended long ago, and its events were delivered to the gateway.
    long_ago = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    run(data / "main_agent.sqlite", "update task_ends set ended_at = ?", (long_ago,))
    run(data / "outbox.sqlite", "update outbox set sent = 1, created_at = ?", (long_ago,))
    events_before = rows(data / "outbox.sqlite", "select count(*) from outbox")[0][0]
    assert events_before > 0

    async with start(read_once) as h:  # the clean-up runs when the service starts, then every hour
        for _ in range(100):
            if not rows(data / "checkpoints.sqlite", "select 1 from checkpoints where thread_id = ?", (task_id,)):
                break
            await asyncio.sleep(0.1)
        assert not rows(data / "checkpoints.sqlite", "select 1 from checkpoints where thread_id = ?", (task_id,))
        assert rows(data / "main_agent.sqlite", "select count(*) from call_marks")[0][0] == 0
        assert rows(data / "outbox.sqlite", "select count(*) from outbox")[0][0] == 0, "delivered and old: gone"
        assert "error" in await h.rpc("GetTask", {"id": task_id}), "the task protocol's own record is gone too"
        assert rows(data / "main_agent.sqlite", "select phase from tasks where task_id = ?", (task_id,)) == [
            ("completed",)
        ], "the task itself stays: it is part of the chat"
        assert rows(data / "main_agent.sqlite", "select count(*) from transcript")[0][0] > 0, "so does what was said"
        assert rows(data / "main_agent.sqlite", "select cleared from task_ends")[0][0] == 1, "done once, not every hour"


@windows_only
async def test_until_deleted_keeps_everything_and_events_not_yet_delivered_are_never_pruned(start) -> None:
    async with start(read_once) as h:
        await h.client.put("/v1/retention", json={"days": 0})
        task_id = await h.new_task("Read old.log")
        await h.wait(task_id, "completed")
        data = h.data_dir
    long_ago = (datetime.now(UTC) - timedelta(days=4000)).isoformat()
    run(data / "main_agent.sqlite", "update task_ends set ended_at = ?", (long_ago,))
    run(data / "outbox.sqlite", "update outbox set created_at = ?", (long_ago,))
    async with start(read_once) as h:
        await asyncio.sleep(0.5)
        assert rows(data / "checkpoints.sqlite", "select 1 from checkpoints where thread_id = ?", (task_id,))
        await h.client.put("/v1/retention", json={"days": 7})
    async with start(read_once) as h:
        await asyncio.sleep(0.5)
        assert rows(data / "outbox.sqlite", "select count(*) from outbox")[0][0] > 0, (
            "unsent events wait for the gateway"
        )


@windows_only
async def test_deleting_a_chat_removes_its_tool_calls_from_the_tool_servers_log(start, tmp_path: Path) -> None:
    log = tmp_path / "data" / "services" / "tool_server" / "proj-1.sqlite"
    async with start(read_once) as h:
        for chat in ("chat-1", "chat-2"):
            await h.wait(await h.new_task("Read old.log", chat_id=chat), "completed")
        assert sorted(rows(log, "select chat_id, tool from calls")) == [("chat-1", "fs.read"), ("chat-2", "fs.read")]
        deleted = await h.client.delete("/v1/chats/chat-1")
        assert deleted.status_code == 200 and deleted.json()["deleted_tasks"] == 1
        assert rows(log, "select chat_id from calls") == [("chat-2",)], "only the deleted chat's calls are gone"
        assert (await h.client.delete("/v1/chats/chat-1")).status_code == 200, "safe to repeat"
        gone = (await h.client.delete("/v1/projects/proj-1")).json()
        assert "proj-1.sqlite" in gone["audit_files_removed"] and not log.exists()
