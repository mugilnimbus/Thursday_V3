"""One tool call of a task, run at most once, with the user asked first when the tool wants that.

- Every call gets a mark keyed by our own ids. A finished call is never re-run when the graph node re-executes;
  a started call without a result reports "outcome unknown".
- When the tool server asks for input, an allow-always rule answers it, otherwise an approval opens and the graph
  interrupts. On resume the call is re-issued (the sealed requestState does not survive restarts) and answered
  from the stored decision.
"""

import logging
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from langgraph.types import interrupt
from mcp_types import CallToolResult, ElicitResult, InputRequiredResult
from thursday_contracts.approvals import ApprovalRequest
from thursday_contracts.events import EventType

from thursday_main_agent.application.ports import Events, ToolCallRecords, ToolServers
from thursday_main_agent.domain.approvals import Approval, ApprovalStatus
from thursday_main_agent.domain.tasks import TaskRecord
from thursday_main_agent.domain.tool_calls import UNKNOWN_OUTCOME, CallMark, MarkState

log = logging.getLogger(__name__)


def tool_text(result: CallToolResult) -> str:
    parts = [getattr(c, "text", None) or f"[{c.type} content]" for c in result.content]
    return "\n".join(parts) or "(no output)"


class ToolCalls:
    def __init__(self, store: ToolCallRecords, events: Events, tools: ToolServers, approval_timeout: timedelta) -> None:
        self._store = store
        self._events = events
        self._tools = tools
        self._approval_timeout = approval_timeout

    async def run(self, task: TaskRecord, key: str, tool: str, args: dict[str, Any]) -> tuple[str, bool]:
        """The call's result as text, and whether it is an error. Must be called from inside a graph node."""
        mark = self._store.get_mark(key)
        if mark is not None and mark.state is MarkState.FINISHED:
            return mark.result or "", mark.is_error
        if mark is not None and mark.state is MarkState.STARTED:
            self._finish(task, key, tool, args, UNKNOWN_OUTCOME, True, "unknown", 0.0)
            return UNKNOWN_OUTCOME, True
        approval = self._store.approval_for_call(key)
        if approval is not None:
            # Every call that has an approval interrupts on every re-run, so LangGraph's positional
            # resume values stay aligned. It returns at once when resumed; the decision is re-read.
            interrupt({"kind": "approval", "approval_id": approval.approval_id})
            approval = self._store.get_approval(approval.approval_id)
        started = time.perf_counter()
        if mark is None:
            self._event(task, key, tool, args, "requested")
        # Conservative: the first leg may run the tool (no approval needed), so it is marked as started.
        self._store.put_mark(CallMark(key, task.task_id, tool, MarkState.STARTED))
        result = await self._tools.call(task.project_id, task.project_folder, tool, args, chat_id=task.chat_id)
        if isinstance(result, InputRequiredResult):
            self._store.put_mark(CallMark(key, task.task_id, tool, MarkState.ASKED))
            action = self._decide(task, key, tool, args, result, approval)
            (request_key,) = (result.input_requests or {"?": None}).keys()
            content: dict[str, Any] | None = {"approve": True} if action == "accept" else None
            self._store.put_mark(CallMark(key, task.task_id, tool, MarkState.STARTED))
            if action == "accept":
                self._event(task, key, tool, args, "running")
            result = await self._tools.call(
                task.project_id,
                task.project_folder,
                tool,
                args,
                input_responses={request_key: ElicitResult(action=action, content=content)},
                request_state=result.request_state,
                chat_id=task.chat_id,
            )
            if isinstance(result, InputRequiredResult):
                text = "The tool asked for input again; the call was not completed."
                self._finish(task, key, tool, args, text, True, "error", time.perf_counter() - started)
                return text, True
        text, is_error = tool_text(result), bool(result.is_error)
        self._finish(
            task, key, tool, args, text, is_error, "error" if is_error else "ok", time.perf_counter() - started
        )
        return text, is_error

    def _decide(
        self,
        task: TaskRecord,
        key: str,
        tool: str,
        args: dict[str, Any],
        asked: InputRequiredResult,
        approval: Approval | None,
    ) -> Literal["accept", "decline", "cancel"]:
        if approval is not None:
            if approval.status is ApprovalStatus.PENDING:
                log.warning("approval %s resumed while still pending; not running the call", approval.approval_id)
            return approval.mcp_action
        if self._store.has_rule(task.chat_id, tool):
            self._events.publish(
                EventType.APPROVAL_RESOLVED,
                {"call_key": key, "tool": tool, "outcome": "allowed", "by": "allow_always_rule"},
                project_id=task.project_id,
                chat_id=task.chat_id,
                task_id=task.task_id,
            )
            return "accept"
        (request,) = (asked.input_requests or {}).values()
        summary = getattr(request.params, "message", "") or f"Run {tool}"
        now = datetime.now(UTC)
        opened = Approval.open(
            f"ap-{uuid.uuid4().hex[:12]}",
            task.task_id,
            task.chat_id,
            key,
            tool,
            summary,
            args,
            now,
            self._approval_timeout,
        )
        self._store.insert_approval(opened)
        request_model = ApprovalRequest(
            approval_id=opened.approval_id,
            task_id=task.task_id,
            chat_id=task.chat_id,
            tool=tool,
            summary=summary[:2000],
            arguments=args,
            expires_at=opened.expires_at,
        )
        self._events.publish(
            EventType.APPROVAL_REQUESTED,
            request_model.model_dump(mode="json"),
            project_id=task.project_id,
            chat_id=task.chat_id,
            task_id=task.task_id,
        )
        interrupt({"kind": "approval", "approval_id": opened.approval_id})
        resolved = self._store.get_approval(opened.approval_id)
        return resolved.mcp_action if resolved is not None else "cancel"

    def _event(self, task: TaskRecord, key: str, tool: str, args: dict[str, Any], status: str) -> None:
        self._events.publish(
            EventType.TOOL_CALL,
            {"call_key": key, "tool": tool, "arguments": args, "status": status},
            project_id=task.project_id,
            chat_id=task.chat_id,
            task_id=task.task_id,
        )

    def _finish(
        self,
        task: TaskRecord,
        key: str,
        tool: str,
        args: dict[str, Any],
        text: str,
        is_error: bool,
        status: str,
        seconds: float,
    ) -> None:
        self._store.put_mark(CallMark(key, task.task_id, tool, MarkState.FINISHED, text, is_error))
        self._events.publish(
            EventType.TOOL_CALL,
            {
                "call_key": key,
                "tool": tool,
                "arguments": args,
                "status": status,
                "result": text,
                "seconds": round(seconds, 3),
            },
            project_id=task.project_id,
            chat_id=task.chat_id,
            task_id=task.task_id,
        )
