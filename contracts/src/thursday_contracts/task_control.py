"""Task-control A2A extension: `PauseTask` and `ResumeTask`.

Declared in the main agent's Agent Card and activated per request with the
`A2A-Extensions` header. Both methods are repeatable and fail on finished tasks.
A paused task stays `WORKING`; its pause state is task metadata under
`PAUSE_STATE_METADATA_KEY`. Stop is the standard `CancelTask`.
"""

from enum import StrEnum

from pydantic import BaseModel

# Placeholder until a permanent home is chosen (open decision in docs/PROJECT.md).
TASK_CONTROL_EXTENSION_URI = "https://thursday.invalid/a2a/ext/task-control/v1"
EXTENSIONS_HEADER = "A2A-Extensions"

PAUSE_TASK_METHOD = "PauseTask"
RESUME_TASK_METHOD = "ResumeTask"
PAUSE_STATE_METADATA_KEY = "pause_state"

# JSON-RPC error codes. -32001 is A2A's TaskNotFound; -32040 is this extension's own.
TASK_NOT_FOUND_CODE = -32001
TASK_NOT_PAUSABLE_CODE = -32040
EXTENSION_NOT_ACTIVATED_CODE = -32601


class PauseState(StrEnum):
    NONE = "none"
    PAUSING = "pausing"
    PAUSED = "paused"


class TaskControlParams(BaseModel):
    id: str


class TaskControlResult(BaseModel):
    id: str
    pause_state: PauseState
