"""Approval request and answer shapes.

The main agent asks through A2A `INPUT_REQUIRED` with an `ApprovalRequest` data
part; clients answer on the same `taskId` and `contextId` with an `ApprovalAnswer`
data part. The first answer wins; later answers get "already resolved".
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

APPROVAL_REQUEST_KIND = "thursday.approval_request"
APPROVAL_ANSWER_KIND = "thursday.approval_answer"


class ApprovalDecision(StrEnum):
    ALLOW_ONCE = "allow_once"
    ALLOW_ALWAYS = "allow_always"
    DENY = "deny"


class ApprovalOutcome(StrEnum):
    """How a request ended. `timed_out` is reported to the tool as MCP `cancel`, `denied` as `decline`."""

    ALLOWED = "allowed"
    DENIED = "denied"
    TIMED_OUT = "timed_out"
    CANCELED = "canceled"


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = APPROVAL_REQUEST_KIND
    approval_id: str
    task_id: str
    chat_id: str
    tool: str
    summary: str = Field(max_length=2000, description="Human-readable description of the action.")
    arguments: dict[str, object] = Field(default_factory=dict)
    expires_at: datetime


class ApprovalAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = APPROVAL_ANSWER_KIND
    approval_id: str
    decision: ApprovalDecision
