"""Context compaction: summarise older turns for the model when the context is nearly full.

The full transcript is never changed. Compaction only changes what the model sees: a summary
message plus the messages after a cut point. The cut never separates a tool call from its
result, and the most recent work (about 40 percent of the window) is kept word for word.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage

CHARS_PER_TOKEN = 3.5
KEEP_FRACTION = 0.4
CHUNK_FRACTION = 0.45
TOOL_RESULT_CHARS = 2000

SUMMARY_INSTRUCTIONS = (
    "You summarise a work conversation between a user and an agent that uses tools on a PC, so the agent can "
    "continue without the full history. Keep: the user's goals and instructions, decisions made, files and "
    "commands touched and their outcomes, errors, approvals denied or not answered, and anything still pending. "
    "Drop greetings and repetition. Write plain, compact notes."
)


def estimate_tokens(messages: list[AnyMessage]) -> int:
    return int(
        sum(len(str(m.content)) + 40 * len(getattr(m, "tool_calls", []) or []) for m in messages) / CHARS_PER_TOKEN
    )


def render(messages: list[AnyMessage]) -> str:
    lines: list[str] = []
    for m in messages:
        if isinstance(m, HumanMessage):
            lines.append(f"USER: {m.text}")
        elif isinstance(m, AIMessage):
            if m.text:
                lines.append(f"AGENT: {m.text}")
            for call in m.tool_calls:
                lines.append(f"AGENT CALLS {call['name']} {call['args']}")
        elif isinstance(m, ToolMessage):
            text = str(m.content)
            lines.append(f"TOOL RESULT: {text[:TOOL_RESULT_CHARS]}" + ("..." if len(text) > TOOL_RESULT_CHARS else ""))
    return "\n".join(lines)


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


Summarise = Callable[[list[AnyMessage]], Awaitable[str]]


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

    def needed(self, view_tokens: int, context_length: int | None) -> bool:
        return bool(context_length) and view_tokens >= self._threshold * context_length  # type: ignore[operator]

    async def compact(
        self, messages: list[AnyMessage], summary: str, upto: int, context_length: int
    ) -> Compacted | None:
        cut = choose_cut(messages, upto, int(context_length * KEEP_FRACTION))
        if cut is None:
            return None
        text = render(messages[upto:cut])
        chunk_chars = int(context_length * CHUNK_FRACTION * CHARS_PER_TOKEN)
        for start in range(0, len(text), chunk_chars):
            piece = text[start : start + chunk_chars]
            prompt = (f"Earlier summary:\n{summary}\n\n" if summary else "") + f"Conversation to add:\n{piece}"
            summary = (await self._summarise([SystemMessage(SUMMARY_INSTRUCTIONS), HumanMessage(prompt)])).strip()
        return Compacted(summary, cut, cut - upto)


def summary_message(summary: str) -> HumanMessage:
    return HumanMessage(f"[Summary of the earlier conversation, for context]\n{summary}")
