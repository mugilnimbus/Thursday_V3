"""Cutting the conversation the voice model is shown down to what fits and what a model accepts.

A model server keeps what it worked out for the start of the last prompt and reuses it when the next prompt
starts the same way. So the window of recent messages does not slide by one message each turn (which would
change the start every time and make the server read everything again): it starts at the same message for
many turns, then jumps forward by a whole step.
"""

from langchain_core.messages import AnyMessage, ToolMessage

CHARS_PER_TOKEN = 3.5


def within_tokens(history: list[AnyMessage], limit: int | None) -> list[AnyMessage]:
    """The newest messages that fit in `limit` tokens (estimated); all of them when no limit is set."""
    if not limit:
        return history
    kept = len(history)
    budget = limit * CHARS_PER_TOKEN
    for index in range(len(history) - 1, -1, -1):
        budget -= len(str(history[index].content)) + 40 * len(getattr(history[index], "tool_calls", []) or [])
        if budget < 0:
            break
        kept = index
    return history[kept:]


def window_start(count: int, most: int, step: int) -> int:
    """Where the window of recent messages starts in a chat of `count` messages: at most `most` messages are
    shown, and the start is always a multiple of `step`, so it moves only once every `step` messages."""
    if count <= most:
        return 0
    return -(-(count - most) // step) * step


def fit_in_steps(history: list[AnyMessage], limit: int | None, step: int) -> list[AnyMessage]:
    """Keep the newest messages that fit in `limit` tokens (estimated), dropping the oldest a whole step at a
    time so the start stays put between drops. All of them when no limit is set."""
    if not limit:
        return history
    budget = limit * CHARS_PER_TOKEN

    def size(messages: list[AnyMessage]) -> float:
        return sum(len(str(m.content)) + 40 * len(getattr(m, "tool_calls", []) or []) for m in messages)

    while len(history) > step and size(history) > budget:
        history = history[step:]
    return within_tokens(history, limit)  # the last step alone can still be too large


def trim_orphans(history: list[AnyMessage]) -> list[AnyMessage]:
    """Drop tool answers at the start of a history window whose call was cut off, which models reject."""
    start = 0
    while start < len(history) and isinstance(history[start], ToolMessage):
        start += 1
    return history[start:]
