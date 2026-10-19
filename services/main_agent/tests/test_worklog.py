"""How a finished task is kept in the chat, and the notes used when the model cannot summarise."""

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from thursday_main_agent.application.compaction import Compactor, render, summary_problem
from thursday_main_agent.application.worklog import MAX_LOG_STEPS, brief_args, compact_task, digest, tool_steps
from thursday_main_agent.domain.tasks import TaskPhase

KEEP_ALMOST_NOTHING = 0.0001  # of a huge window: the cut falls just before the final steps


def used(name: str, args: dict, id_: str, result: str, error: bool = False) -> list[AnyMessage]:
    return [
        AIMessage("", tool_calls=[{"name": name, "args": args, "id": id_}]),
        ToolMessage(result, tool_call_id=id_, status="error" if error else "success"),
    ]


def a_task_with_a_failed_edit() -> list[AnyMessage]:
    return [
        HumanMessage("Fix main.py"),
        *used("fs_read", {"path": "main.py"}, "1", "x" * 1204),
        *used("fs_edit", {"path": "main.py", "old_string": "foo"}, "2", "old_string not found\nin main.py", error=True),
        *used("fs_edit", {"path": "main.py", "old_string": "foo"}, "3", "edited"),
        AIMessage("Fixed it."),
    ]


def test_a_finished_task_is_stored_as_the_instruction_and_a_record() -> None:
    first, second = compact_task("Fix main.py", a_task_with_a_failed_edit(), TaskPhase.COMPLETED, "Fixed it.")
    assert isinstance(first, HumanMessage) and first.text == "Fix main.py"
    assert isinstance(second, AIMessage) and not second.tool_calls
    lines = second.text.splitlines()
    assert "1. fs_read [path=main.py] -> ok, 1204 chars" in lines
    assert "2. fs_edit [path=main.py, old_string=foo] -> FAILED: old_string not found" in lines
    assert "3. fs_edit [path=main.py, old_string=foo] -> ok, 6 chars (again; first at step 2)" in lines
    assert second.text.endswith("[Final message]\nFixed it.")
    assert "x" * 50 not in second.text, "raw tool output is not kept"


def test_a_task_without_tools_and_a_task_that_ended_badly_say_so() -> None:
    (_, none), (_, failed), (_, stopped) = (
        compact_task("Hi", [HumanMessage("Hi")], TaskPhase.COMPLETED, "Hello"),
        compact_task("Hi", [], TaskPhase.FAILED, "The model ran out of context window."),
        compact_task("Hi", [], TaskPhase.CANCELED, "Stopped by the user."),
    )
    assert "it used no tools" in none.text
    assert "[The task failed]\nThe model ran out" in failed.text
    assert "[The task was stopped by the user before it finished]" in stopped.text


def test_a_call_without_a_result_is_reported() -> None:
    call = AIMessage("", tool_calls=[{"name": "fs_delete", "args": {"path": "a"}, "id": "9"}])
    (step,) = tool_steps([call])
    assert not step.ok and step.note == "no result was recorded"


def test_a_very_long_log_keeps_both_ends_and_counts_the_middle() -> None:
    messages: list[AnyMessage] = []
    for i in range(200):
        messages += used("fs_read", {"path": f"f{i}"}, str(i), "ok", error=(i % 10 == 0))
    record = compact_task("Read lots", messages, TaskPhase.COMPLETED, "done")[1].text
    assert "1. fs_read [path=f0]" in record and "200. fs_read [path=f199]" in record
    assert f"{200 - MAX_LOG_STEPS} more steps omitted" in record
    assert len(record.splitlines()) < MAX_LOG_STEPS + 10


def test_arguments_are_shortened_and_never_look_like_json() -> None:
    text = brief_args({"path": "a.txt", "content": "line\n" * 500, "n": 3})
    assert text.startswith("path=a.txt, content=line line") and "{" not in text and len(text) <= 160


# --- summaries ------------------------------------------------------------------------------------
def test_the_summariser_is_shown_tool_calls_as_description_not_syntax() -> None:
    text = render(a_task_with_a_failed_edit())
    assert "AGENT USED TOOL fs_edit on [path=main.py, old_string=foo]" in text
    assert "RESULT of fs_edit (FAILED): old_string not found" in text
    assert "AGENT CALLS" not in text and "{'path'" not in text


def test_summaries_that_are_tool_calls_or_too_short_are_rejected() -> None:
    notes = "The user asked to fix main.py. The agent read it, then edited it after one failed attempt."
    assert summary_problem(notes) is None
    assert "tool-call syntax" in (summary_problem('<|tool_call>call:fs_read{path:<|"|>x<|"|>}<tool_call|>' * 3) or "")
    assert "tool-call syntax" in (summary_problem('```\ncall:fs_read{path:"x"} ' + notes) or "")
    assert "tool-call syntax" in (summary_problem(notes + " <tool_call|>") or "")
    assert "characters" in (summary_problem("ok") or "")
    assert summary_problem("") is not None


async def test_a_bad_summary_is_asked_for_again_with_a_firmer_request() -> None:
    asked: list[tuple[str, str]] = []
    replies = iter(['<|tool_call>call:fs_read{path:"x"}<tool_call|>' * 4, "short", "Good notes. " * 10])

    async def summarise(messages: list[AnyMessage]) -> str:
        asked.append((str(messages[0].content), str(messages[1].content)))
        return next(replies)

    done = await Compactor(summarise, 90).compact(a_task_with_a_failed_edit(), "", 0, 100_000, KEEP_ALMOST_NOTHING)
    assert done is not None and done.summary.startswith("Good notes.") and not done.from_digest
    assert len(asked) == 3
    assert "do not call tools" not in asked[0][0]
    assert all("Write notes, do not call tools" in system and "do not call tools" in user for system, user in asked[1:])


async def test_if_the_model_never_writes_notes_they_are_built_without_it() -> None:
    async def summarise(messages: list[AnyMessage]) -> str:
        return "<|tool_call>call:fs_read{}<tool_call|>"

    done = await Compactor(summarise, 90).compact(
        a_task_with_a_failed_edit(), "Earlier notes.", 0, 100_000, KEEP_ALMOST_NOTHING
    )
    assert done is not None and done.from_digest
    assert done.summary.startswith("Earlier notes.\n\nThe user asked: Fix main.py")
    assert "FAILED: old_string not found" in done.summary and "<|tool_call>" not in done.summary


def test_the_digest_is_bounded() -> None:
    assert len(digest([HumanMessage("x" * 100_000)] * 100)) <= 6000


async def test_the_summary_limit_is_the_chosen_token_count_capped_by_the_window() -> None:
    async def summarise(_: list[AnyMessage]) -> str:
        return ""

    compactor = Compactor(summarise, 90)
    assert compactor.limit(100_000) == 90_000, "nothing chosen: 90 percent of the loaded window"
    assert compactor.limit(100_000, 32_768) == 32_768
    assert compactor.limit(16_384, 131_072) == 14_745, "a choice larger than the window cannot overflow it"
    assert compactor.limit(None, 65_536) == 65_536, "a cloud endpoint reports no window: the choice is the limit"
    assert compactor.limit(None) is None and not compactor.needed(10**9, None)
    assert compactor.needed(70_000, None, 65_536) and not compactor.needed(60_000, None, 65_536)
