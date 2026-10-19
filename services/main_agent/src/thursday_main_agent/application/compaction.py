"""Context compaction: summarise older turns for the model when the context is nearly full.

The full transcript is never changed. Compaction only changes what the model sees: a summary
message plus the messages after a cut point. The cut never separates a tool call from its
result, and the most recent work (about 40 percent of the window) is kept word for word.

A summary that is too short or is tool-call syntax is rejected and asked for again; if the model
still cannot write notes, plain notes are built from the messages without it.
"""

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage

from thursday_main_agent.application.worklog import brief_args, digest

log = logging.getLogger(__name__)
CHARS_PER_TOKEN = 3.5
KEEP_FRACTION = 0.4
HARDER_KEEP_FRACTION = 0.15  # used after the window overflowed: keep less word for word
CHUNK_FRACTION = 0.45
TOOL_RESULT_CHARS = 2000
MIN_SUMMARY_CHARS = 60
SUMMARY_ATTEMPTS = 3

SUMMARY_INSTRUCTIONS = (
    "You summarise a work conversation between a user and an agent that uses tools on a PC, so the agent can "
    "continue without the full history. Keep: the user's goals and instructions, decisions made, files and "
    "commands touched and their outcomes, errors, approvals denied or not answered, and anything still pending. "
    "Drop greetings and repetition. Write plain, compact notes."
)
NOTES_ONLY = "Write notes, do not call tools. Reply with plain sentences only, never with tool-call syntax."
TOOL_SYNTAX = re.compile(r"^[\s`]*(<\|?tool_call|call:\w+|\[TOOL_CALLS\]|<\|\"\|>|\{\s*\"name\")", re.IGNORECASE)
TOOL_TOKENS = ("<|tool_call>", "<tool_call|>")


def estimate_tokens(messages: list[AnyMessage]) -> int:
    return int(
        sum(len(str(m.content)) + 40 * len(getattr(m, "tool_calls", []) or []) for m in messages) / CHARS_PER_TOKEN
    )


def render(messages: list[AnyMessage]) -> str:
    """The conversation as plain text for the summariser. Tool calls are described, never written as calls."""
    lines: list[str] = []
    tools: dict[str, str] = {}
    for m in messages:
        if isinstance(m, HumanMessage):
            lines.append(f"USER: {m.text}")
        elif isinstance(m, AIMessage):
            if m.text:
                lines.append(f"AGENT: {m.text}")
            for call in m.tool_calls:
                tools[call["id"] or ""] = call["name"]
                lines.append(f"AGENT USED TOOL {call['name']} on [{brief_args(call['args'])}]")
        elif isinstance(m, ToolMessage):
            text = str(m.content)
            outcome = "FAILED" if m.status == "error" else "ok"
            more = "..." if len(text) > TOOL_RESULT_CHARS else ""
            lines.append(
                f"RESULT of {tools.get(m.tool_call_id, 'a tool')} ({outcome}): {text[:TOOL_RESULT_CHARS]}{more}"
            )
    return "\n".join(lines)


def summary_problem(text: str) -> str | None:
    """Why a summary cannot be used, or None when it can."""
    text = text.strip()
    if TOOL_SYNTAX.match(text) or any(token in text for token in TOOL_TOKENS):
        return "tool-call syntax instead of notes"
    if len(text) < MIN_SUMMARY_CHARS:
        return f"only {len(text)} characters"
    return None


def is_boundary(message: AnyMessage) -> bool:
    """A cut may start a kept tail only at a user message or an agent message, never at a tool result."""
    return isinstance(message, HumanMessage | AIMessage)


def choose_cut(messages: list[AnyMessage], already_upto: int, keep_tokens: int) -> int | None:
    """Index where the kept tail starts, or None when nothing more can be summarised."""
    kept = 0
    cut = len(messages)
    for index in range(len(messages) - 1, already_upto - 1, -1):
        kept += estimate_tokens([messages[index]])
        cut = index
        if kept >= keep_tokens:
            break
    while cut < len(messages) and not is_boundary(messages[cut]):
        cut += 1
    if cut >= len(messages):
        # The newest step alone exceeds the budget: keep just that step, summarise the rest.
        cut = next((i for i in range(len(messages) - 1, already_upto, -1) if is_boundary(messages[i])), already_upto)
    return cut if already_upto < cut < len(messages) else None


@dataclass(frozen=True, slots=True)
class Compacted:
    summary: str
    upto: int
    summarised_messages: int
    from_digest: bool = False  # the model could not write usable notes, so they were built without it


Summarise = Callable[[list[AnyMessage]], Awaitable[str]]


class UnusableSummary(Exception):
    pass


class Compactor:
    def __init__(self, summarise: Summarise, threshold_percent: float) -> None:
        self._summarise = summarise
        self._threshold = threshold_percent / 100

    @property
    def threshold_percent(self) -> float:
        return self._threshold * 100

    @threshold_percent.setter
    def threshold_percent(self, value: float) -> None:
        self._threshold = value / 100

    def limit(self, context_length: int | None, compact_at_tokens: int | None = None) -> int | None:
        """The view size that triggers a summary: the chosen token count, never more than the share of the window
        that is safe. None when neither is known (a cloud endpoint with no token count chosen)."""
        limits = [compact_at_tokens, int(self._threshold * context_length) if context_length else None]
        known = [value for value in limits if value]
        return min(known) if known else None

    def needed(self, view_tokens: int, context_length: int | None, compact_at_tokens: int | None = None) -> bool:
        limit = self.limit(context_length, compact_at_tokens)
        return limit is not None and view_tokens >= limit

    async def compact(
        self,
        messages: list[AnyMessage],
        summary: str,
        upto: int,
        context_length: int,
        keep_fraction: float = KEEP_FRACTION,
    ) -> Compacted | None:
        cut = choose_cut(messages, upto, int(context_length * keep_fraction))
        if cut is None:
            return None
        text = render(messages[upto:cut])
        chunk_chars = int(context_length * CHUNK_FRACTION * CHARS_PER_TOKEN)
        earlier = summary
        try:
            for start in range(0, len(text), chunk_chars):
                piece = text[start : start + chunk_chars]
                summary = await self._notes(
                    (f"Earlier summary:\n{summary}\n\n" if summary else "") + f"Conversation to add:\n{piece}"
                )
        except UnusableSummary:
            notes = digest(messages[upto:cut])
            return Compacted(f"{earlier}\n\n{notes}" if earlier else notes, cut, cut - upto, from_digest=True)
        return Compacted(summary, cut, cut - upto)

    async def _notes(self, prompt: str) -> str:
        """Ask for notes; reject tool-call syntax or a too-short answer and ask again, firmly."""
        instructions = SUMMARY_INSTRUCTIONS
        for attempt in range(1, SUMMARY_ATTEMPTS + 1):
            text = (await self._summarise([SystemMessage(instructions), HumanMessage(prompt)])).strip()
            problem = summary_problem(text)
            if problem is None:
                return text
            log.warning("summary attempt %d of %d rejected: %s", attempt, SUMMARY_ATTEMPTS, problem)
            if attempt == 1:
                instructions = f"{SUMMARY_INSTRUCTIONS} {NOTES_ONLY}"
                prompt = f"{prompt}\n\n{NOTES_ONLY}"
        raise UnusableSummary(f"no usable summary after {SUMMARY_ATTEMPTS} attempts")


def summary_message(summary: str) -> HumanMessage:
    return HumanMessage(f"[Summary of the earlier conversation, for context]\n{summary}")
