"""Short records of agent work: a finished task as the chat transcript keeps it, and notes for summarising.

The transcript keeps only what the next task needs: what was asked, which tools ran and how each one
ended, and the final message. Raw tool output stays in the task trace, not in the model's history.
Nothing here is written as a tool call, so a model that reads it is not nudged to imitate one.
"""

import json
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage

from thursday_main_agent.domain.tasks import TaskPhase

ARG_CHARS = 60
ARGS_CHARS = 160
NOTE_CHARS = 140
SAID_CHARS = 300
ASKED_CHARS = 400
MAX_LOG_STEPS = 80
DIGEST_CHARS = 6000
ENDINGS = {
    TaskPhase.COMPLETED: "[Final message]",
    TaskPhase.FAILED: "[The task failed]",
    TaskPhase.CANCELED: "[The task was stopped by the user before it finished]",
}


@dataclass(frozen=True, slots=True)
class ToolStep:
    tool: str
    args: str
    ok: bool
    note: str  # "1204 chars" for a success; what went wrong for a failure


def clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def brief_args(args: dict[str, Any]) -> str:
    """`path=main.py, old_string=...`: enough to tell calls apart, and not call syntax."""
    parts = [
        f"{key}={clip(value if isinstance(value, str) else json.dumps(value, default=str), ARG_CHARS)}"
        for key, value in args.items()
    ]
    return clip(", ".join(parts), ARGS_CHARS)


def tool_steps(messages: list[AnyMessage]) -> list[ToolStep]:
    """Every tool call in order, paired with how it ended."""
    results = {m.tool_call_id: m for m in messages if isinstance(m, ToolMessage)}
    steps: list[ToolStep] = []
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        for call in message.tool_calls:
            result = results.get(call["id"] or "")
            args = brief_args(call["args"])
            if result is None:
                steps.append(ToolStep(call["name"], args, False, "no result was recorded"))
                continue
            text = str(result.content).strip()
            if result.status == "error":
                first_line = text.splitlines()[0] if text else "no message"
                steps.append(ToolStep(call["name"], args, False, clip(first_line, NOTE_CHARS)))
            else:
                steps.append(ToolStep(call["name"], args, True, f"{len(text)} chars" if text else "no output"))
    return steps


def log_lines(steps: list[ToolStep]) -> list[str]:
    """One line per step; a call repeated with the same arguments says so; a very long log keeps both ends."""
    first_seen: dict[tuple[str, str], int] = {}
    lines: list[str] = []
    for number, step in enumerate(steps, start=1):
        key = (step.tool, step.args)
        repeat = f" (again; first at step {first_seen[key]})" if key in first_seen else ""
        first_seen.setdefault(key, number)
        outcome = f"ok, {step.note}" if step.ok else f"FAILED: {step.note}"
        lines.append(f"{number}. {step.tool} [{step.args}] -> {outcome}{repeat}")
    if len(lines) <= MAX_LOG_STEPS:
        return lines
    half = MAX_LOG_STEPS // 2
    omitted = steps[half:-half]
    failed = sum(1 for s in omitted if not s.ok)
    note = f"... {len(omitted)} more steps omitted ({len(omitted) - failed} ok, {failed} failed) ..."
    return [*lines[:half], note, *lines[-half:]]


def compact_task(
    instruction: str, own_messages: list[AnyMessage], ended: TaskPhase, final_text: str
) -> list[AnyMessage]:
    """The two messages a finished task leaves in the chat: the instruction, then the tool log and final message."""
    steps = tool_steps(own_messages)
    record = (
        "[Record of this finished task: the tools it ran and how each one ended]\n" + "\n".join(log_lines(steps))
        if steps
        else "[Record of this finished task: it used no tools]"
    )
    heading = ENDINGS.get(ended, "[How the task ended]")
    return [HumanMessage(instruction), AIMessage(f"{record}\n\n{heading}\n{final_text.strip() or '(no message)'}")]


def digest(messages: list[AnyMessage]) -> str:
    """Plain notes built without a model, for when the model cannot write a usable summary."""
    lines: list[str] = []
    for message in messages:
        if isinstance(message, HumanMessage):
            lines.append(f"The user asked: {clip(message.text, ASKED_CHARS)}")
        elif isinstance(message, AIMessage) and message.text.strip():
            lines.append(f"The agent said: {clip(message.text, SAID_CHARS)}")
    steps = tool_steps(messages)
    if steps:
        lines.append("Tools the agent ran, in order:")
        lines.extend(log_lines(steps))
    text = "\n".join(lines)
    return text if len(text) <= DIGEST_CHARS else text[: DIGEST_CHARS - 1] + "…"
