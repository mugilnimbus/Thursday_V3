import json
import shutil
import sqlite3
import sys

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from thursday_main_agent.application.compaction import choose_cut


def test_cut_never_starts_at_a_tool_result() -> None:
    call = AIMessage("", tool_calls=[{"name": "fs_read", "args": {}, "id": "a"}])
    messages = [HumanMessage("x" * 400), call, ToolMessage("y" * 400, tool_call_id="a"), AIMessage("done")]
    cut = choose_cut(messages, 0, keep_tokens=100)  # pyright: ignore[reportArgumentType]
    assert cut is not None and not isinstance(messages[cut], ToolMessage)


def test_nothing_to_cut_returns_none() -> None:
    assert choose_cut([HumanMessage("short")], 0, keep_tokens=10_000) is None  # pyright: ignore[reportArgumentType]


GOOD_SUMMARY = "SUMMARY: the agent read big.txt several times; it has 400 lines and nothing else needs doing."
windows_only = pytest.mark.skipif(
    sys.platform != "win32" and shutil.which("pwsh") is None, reason="the shell tools need Windows or pwsh"
)


def is_summary_request(messages: list[BaseMessage]) -> bool:
    return isinstance(messages[0], SystemMessage) and str(messages[0].content).startswith("You summarise")


def reads_until_done(messages: list[BaseMessage]) -> AIMessage:
    if is_summary_request(messages):
        return AIMessage(GOOD_SUMMARY)
    summarised = any(isinstance(m, HumanMessage) and m.text.startswith("[Summary of the earlier") for m in messages)
    assert any(isinstance(m, HumanMessage) and m.text == "Read big.txt carefully" for m in messages), "instruction kept"
    reads = [m for m in messages if isinstance(m, ToolMessage)]
    if len(reads) < 6 and not summarised:
        return AIMessage("", tool_calls=[{"name": "fs_read", "args": {"path": "big.txt"}, "id": f"r{len(reads)}"}])
    return AIMessage("done with summary" if summarised else "done without summary")


def saved(h, query: str, *args) -> list:
    db = sqlite3.connect(h.data_dir / "main_agent.sqlite")
    try:
        return db.execute(query, args).fetchall()
    finally:
        db.close()


@windows_only
async def test_long_task_compacts_and_is_stored_as_instruction_tool_log_and_final_message(start, workspace) -> None:
    (workspace / "big.txt").write_text("\n".join(f"line {i} " + "x" * 30 for i in range(400)), encoding="utf-8")
    async with start(reads_until_done, context_length=6000) as h:
        task_id = await h.new_task("Read big.txt carefully")
        done = await h.wait(task_id, "completed", timeout=60)
        assert done["artifacts"][0]["parts"][0]["text"] == "done with summary"
        (event,) = await h.events("compaction")
        payload = event["payload"]
        assert payload["estimated_tokens_after"] < payload["estimated_tokens_before"]
        assert payload["summary"].startswith("SUMMARY") and not payload["from_digest"]
    rows = [json.loads(r[0]) for r in saved(h, "select message from transcript order by id")]
    assert [r["type"] for r in rows] == ["human", "ai"], "two messages, not every tool result"
    assert rows[0]["data"]["content"] == "Read big.txt carefully"
    record = rows[1]["data"]["content"]
    assert record.count("fs_read [path=big.txt] -> ok") == 2 and "line 399" not in record
    assert record.endswith("[Final message]\ndone with summary")


@windows_only
async def test_a_summary_written_mid_task_is_kept_for_the_next_task(start, workspace) -> None:
    (workspace / "big.txt").write_text("\n".join(f"line {i} " + "x" * 30 for i in range(400)), encoding="utf-8")
    third_saw: list[BaseMessage] = []

    def script(messages: list[BaseMessage]) -> AIMessage:
        if is_summary_request(messages):
            return AIMessage(GOOD_SUMMARY)
        asked = next(
            m.text for m in reversed(messages) if isinstance(m, HumanMessage) and not m.text.startswith("[Sum")
        )
        if asked == "Say hi":
            return AIMessage("hi")
        if asked == "And now?":
            third_saw[:] = messages
            return AIMessage("ok")
        return reads_until_done(messages)

    async with start(script, context_length=6000) as h:
        await h.wait(await h.new_task("Say hi"), "completed")
        await h.wait(await h.new_task("Read big.txt carefully"), "completed", timeout=60)
        assert len(await h.events("compaction")) == 1
        await h.wait(await h.new_task("And now?"), "completed")
    ((upto, summary),) = saved(h, "select upto, summary from chat_summaries")
    assert upto == 2, "the summary covers the history before the second task; that task follows it in full"
    assert summary == GOOD_SUMMARY
    kinds = [(m.type, m.text[:24]) for m in third_saw]
    assert kinds[1][1].startswith("[Summary of the earlier"), kinds
    assert kinds[2] == ("human", "Read big.txt carefully")
    assert kinds[3][0] == "ai" and "fs_read [path=big.txt]" in third_saw[3].text
    assert kinds[-1] == ("human", "And now?") and len(kinds) == 5


@windows_only
async def test_a_summary_that_is_tool_call_syntax_is_rejected_and_asked_for_again(start, workspace) -> None:
    (workspace / "big.txt").write_text("\n".join(f"line {i} " + "x" * 30 for i in range(400)), encoding="utf-8")
    asked_with: list[str] = []

    def script(messages: list[BaseMessage]) -> AIMessage:
        if is_summary_request(messages):
            system = str(messages[0].content)
            asked_with.append(system)
            return AIMessage(
                GOOD_SUMMARY if "do not call tools" in system else '<|tool_call>call:fs_read{path:"x"}<tool_call|>'
            )
        return reads_until_done(messages)

    async with start(script, context_length=6000) as h:
        await h.wait(await h.new_task("Read big.txt carefully"), "completed", timeout=60)
        (event,) = await h.events("compaction")
        assert event["payload"]["summary"] == GOOD_SUMMARY and not event["payload"]["from_digest"]
    firm = ["do not call tools" in system for system in asked_with]
    assert len(firm) >= 2 and firm == [False, True] * (len(firm) // 2), "each chunk is asked once, then firmly"
