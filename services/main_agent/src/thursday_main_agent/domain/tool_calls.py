"""Tool-call identity and naming.

Call keys are ours, never the provider's: LM Studio's tool-call IDs are a counter that can
repeat after the endpoint restarts (spike S3). A key is task, step, and position.

MCP tool names may contain dots (`fs.read`); OpenAI-style function names may not. The
name map is a bijection built from the server's tool list.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
MAX_LLM_NAME = 64


def call_key(task_id: str, step: int, index: int) -> str:
    return f"{task_id}:{step}:{index}"


class MarkState(StrEnum):
    STARTED = "started"
    ASKED = "asked"
    FINISHED = "finished"


@dataclass(frozen=True, slots=True)
class CallMark:
    """Written before a call that may run; a STARTED mark without FINISHED after a restart means
    the outcome is unknown and the call must not be blindly re-run."""

    key: str
    task_id: str
    tool: str
    state: MarkState
    result: str | None = None
    is_error: bool = False


UNKNOWN_OUTCOME = (
    "Outcome unknown: this tool call started before a restart and its result was lost. "
    "Check the current state (for example read the file or list the folder) before trying again."
)


class ToolNameMap:
    def __init__(self, mcp_names: list[str]) -> None:
        self._to_llm: dict[str, str] = {}
        self._to_mcp: dict[str, str] = {}
        for name in sorted(mcp_names):
            base = _UNSAFE.sub("_", name)[:MAX_LLM_NAME] or "tool"
            candidate, n = base, 2
            while candidate in self._to_mcp:
                suffix = f"_{n}"
                candidate, n = base[: MAX_LLM_NAME - len(suffix)] + suffix, n + 1
            self._to_llm[name], self._to_mcp[candidate] = candidate, name

    def to_llm(self, mcp_name: str) -> str:
        return self._to_llm[mcp_name]

    def to_mcp(self, llm_name: str) -> str | None:
        return self._to_mcp.get(llm_name)
