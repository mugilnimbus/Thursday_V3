"""Approval requests and their rules.

An approval is pending until the first human answer, the timeout, or task cancellation.
The first answer wins; any later answer is rejected as already resolved. A timeout is
reported to the tool as MCP `cancel` ("user did not respond"), a denial as `decline`.
Two timeouts in a row pause the task.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal

from thursday_contracts.approvals import ApprovalDecision

McpAction = Literal["accept", "decline", "cancel"]


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    ALLOWED = "allowed"
    DENIED = "denied"
    TIMED_OUT = "timed_out"
    CANCELED = "canceled"


class ApprovalAlreadyResolved(Exception):
    def __init__(self, approval_id: str, status: ApprovalStatus) -> None:
        super().__init__(f"approval {approval_id} is already {status}")
        self.status = status


@dataclass(slots=True)
class Approval:
    approval_id: str
    task_id: str
    chat_id: str
    call_key: str
    tool: str
    summary: str
    arguments: dict[str, object]
    created_at: datetime
    expires_at: datetime
    status: ApprovalStatus = ApprovalStatus.PENDING
    decision: ApprovalDecision | None = None
    resolved_by: str | None = None

    @classmethod
    def open(
        cls,
        approval_id: str,
        task_id: str,
        chat_id: str,
        call_key: str,
        tool: str,
        summary: str,
        arguments: dict[str, object],
        now: datetime,
        timeout: timedelta,
    ) -> "Approval":
        return cls(approval_id, task_id, chat_id, call_key, tool, summary, arguments, now, now + timeout)

    def answer(self, decision: ApprovalDecision, by: str, now: datetime) -> None:
        if self.status is not ApprovalStatus.PENDING:
            raise ApprovalAlreadyResolved(self.approval_id, self.status)
        if now >= self.expires_at:
            self.expire()
            raise ApprovalAlreadyResolved(self.approval_id, self.status)
        self.decision = decision
        self.resolved_by = by
        self.status = ApprovalStatus.DENIED if decision is ApprovalDecision.DENY else ApprovalStatus.ALLOWED

    def expire(self) -> None:
        if self.status is ApprovalStatus.PENDING:
            self.status = ApprovalStatus.TIMED_OUT

    def cancel(self) -> None:
        if self.status is ApprovalStatus.PENDING:
            self.status = ApprovalStatus.CANCELED

    def is_due(self, now: datetime) -> bool:
        return self.status is ApprovalStatus.PENDING and now >= self.expires_at

    @property
    def mcp_action(self) -> McpAction:
        return {ApprovalStatus.ALLOWED: "accept", ApprovalStatus.DENIED: "decline"}.get(self.status, "cancel")  # type: ignore[return-value]


@dataclass(slots=True)
class TimeoutStreak:
    """Consecutive approval timeouts in one task; any human answer resets it."""

    limit: int
    count: int = 0

    def record(self, status: ApprovalStatus) -> bool:
        """Returns True when the task must pause."""
        if status is ApprovalStatus.TIMED_OUT:
            self.count += 1
        elif status in (ApprovalStatus.ALLOWED, ApprovalStatus.DENIED):
            self.count = 0
        return self.count >= self.limit


@dataclass(frozen=True, slots=True)
class AllowRule:
    """ "Allow always" for one tool, only inside one chat."""

    chat_id: str
    tool: str
    created_at: datetime = field(compare=False)

    def covers(self, chat_id: str, tool: str) -> bool:
        return self.chat_id == chat_id and self.tool == tool
