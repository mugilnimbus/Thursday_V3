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


def reads_until_done(messages: list[BaseMessage]) -> AIMessage:
    if isinstance(messages[0], SystemMessage) and str(messages[0].content).startswith("You summarise"):
        return AIMessage("SUMMARY: the agent read big.txt several times; it has 400 lines.")
    summarised = any(isinstance(m, HumanMessage) and m.text.startswith("[Summary of the earlier") for m in messages)
    assert any(isinstance(m, HumanMessage) and m.text == "Read big.txt carefully" for m in messages), "instruction kept"
    reads = [m for m in messages if isinstance(m, ToolMessage)]
    if len(reads) < 6 and not summarised:
        return AIMessage("", tool_calls=[{"name": "fs_read", "args": {"path": "big.txt"}, "id": f"r{len(reads)}"}])
    return AIMessage("done with summary" if summarised else "done without summary")


@pytest.mark.skipif(sys.platform != "win32", reason="tool server targets Windows")
async def test_long_task_compacts_and_keeps_the_full_transcript(start, workspace) -> None:
    (workspace / "big.txt").write_text("\n".join(f"line {i} " + "x" * 30 for i in range(400)), encoding="utf-8")
    async with start(reads_until_done, context_length=6000) as h:
        task_id = await h.new_task("Read big.txt carefully")
        done = await h.wait(task_id, "completed", timeout=60)
        assert done["artifacts"][0]["parts"][0]["text"] == "done with summary"
        (event,) = await h.events("compaction")
        payload = event["payload"]
        assert payload["estimated_tokens_after"] < payload["estimated_tokens_before"]
        assert payload["summary"].startswith("SUMMARY")
    db = sqlite3.connect(h.data_dir / "main_agent.sqlite")
    try:
        saved = db.execute('select count(*) from transcript where message like \'%"type": "tool"%\'').fetchone()[0]
    finally:
        db.close()
    assert saved >= 2, "the full transcript keeps every tool result"
