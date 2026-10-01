"""Task control and approval answers, straight to the main agent (independent of the voice agent)."""

from typing import Any

from thursday_contracts.approvals import ApprovalDecision

from thursday_gateway.application.projects import NotFound
from thursday_gateway.infrastructure.agents import MainAgentClient
from thursday_gateway.infrastructure.store import Store


class TaskControl:
    def __init__(self, store: Store, main: MainAgentClient) -> None:
        self._store = store
        self._main = main

    def _task_row(self, task_id: str) -> Any:
        rows = self._store.query("select * from tasks where task_id = ?", (task_id,))
        if not rows:
            raise NotFound(task_id)
        return rows[0]

    async def pause(self, task_id: str) -> dict[str, Any]:
        self._task_row(task_id)
        return await self._main.pause(task_id)

    async def resume(self, task_id: str) -> dict[str, Any]:
        self._task_row(task_id)
        return await self._main.resume(task_id)

    async def stop(self, task_id: str) -> dict[str, Any]:
        self._task_row(task_id)
        return await self._main.cancel(task_id)

    async def answer(self, approval_id: str, decision: ApprovalDecision) -> None:
        rows = self._store.query("select * from approvals where approval_id = ?", (approval_id,))
        if not rows:
            raise NotFound(approval_id)
        row = rows[0]
        await self._main.answer_approval(row["task_id"], row["chat_id"], approval_id, decision.value)
