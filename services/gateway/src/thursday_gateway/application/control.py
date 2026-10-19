"""Task control and approval answers, straight to the main agent (independent of the voice agent)."""

from typing import Any

from thursday_contracts.approvals import ApprovalDecision

from thursday_gateway.application.ports import MainAgent, TaskLookup
from thursday_gateway.application.projects import NotFound


class TaskControl:
    def __init__(self, lookup: TaskLookup, main: MainAgent) -> None:
        self._lookup = lookup
        self._main = main

    def _known(self, task_id: str) -> None:
        if self._lookup.task(task_id) is None:
            raise NotFound(task_id)

    async def pause(self, task_id: str) -> dict[str, Any]:
        self._known(task_id)
        return await self._main.pause(task_id)

    async def resume(self, task_id: str) -> dict[str, Any]:
        self._known(task_id)
        return await self._main.resume(task_id)

    async def stop(self, task_id: str) -> dict[str, Any]:
        self._known(task_id)
        return await self._main.cancel(task_id)

    async def answer(self, approval_id: str, decision: ApprovalDecision) -> None:
        approval = self._lookup.approval(approval_id)
        if approval is None:
            raise NotFound(approval_id)
        await self._main.answer_approval(approval["task_id"], approval["chat_id"], approval_id, decision.value)
