"""Checks on the voice model's report of a finished direct task.

The model only phrases the report; code decides whether to trust it. A report that is empty, is
tool-call syntax, claims work is being delegated or in progress, or runs on is dropped, and the
main agent's own words are shown instead.
"""

import re

MAX_REPORT_CHARS = 1500
RESULT_CHARS = 4000  # how much of the main agent's result the voice model is shown
TOOL_SYNTAX = re.compile(r"^[\s`]*(<\|?tool_call|call:\w+|\[TOOL_CALLS\]|<\|\"\|>|\{\s*\"name\")", re.IGNORECASE)
TOOL_TOKENS = ("<|tool_call>", "<tool_call|>")
WRONG_FRAME = re.compile(r"\b(delegat\w*|in progress|passed (it|that|this) on)\b", re.IGNORECASE)


def report_problem(text: str) -> str | None:
    """Why a report cannot be used, or None when it can."""
    text = text.strip()
    if not text:
        return "empty"
    if TOOL_SYNTAX.match(text) or any(token in text for token in TOOL_TOKENS):
        return "tool-call syntax"
    if WRONG_FRAME.search(text):
        return "talks about delegating or progress, not a result"
    if len(text) > MAX_REPORT_CHARS:
        return "too long"
    return None


def finished_note(short_id: str, result: str) -> str:
    """The tool answer the voice model is shown, as if it had delegated the task itself."""
    text = result.strip()
    text = text if len(text) <= RESULT_CHARS else text[:RESULT_CHARS] + " ..."
    return f"Task {short_id} finished. The main agent's result: {text}"


def started_note(short_id: str) -> str:
    """The tool answer recorded when a direct task starts: the outcome is not known yet."""
    return f"Task {short_id} started in the background. The result arrives later, so the outcome is not known yet."
