"""`application/problem+json` error bodies with stable codes (RFC 9457)."""

from enum import StrEnum

from pydantic import BaseModel

PROBLEM_MEDIA_TYPE = "application/problem+json"


class ProblemCode(StrEnum):
    UNAUTHENTICATED = "unauthenticated"
    NOT_FOUND = "not_found"
    APPROVAL_ALREADY_RESOLVED = "approval_already_resolved"
    TASK_NOT_PAUSABLE = "task_not_pausable"
    INVALID_INPUT = "invalid_input"
    DEPENDENCY_DOWN = "dependency_down"
    CONFLICT = "conflict"
    RATE_LIMITED = "rate_limited"


class Problem(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    code: ProblemCode
    detail: str = ""
