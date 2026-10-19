"""This service's part of deleting a chat or a project: everything it holds for it goes. Safe to repeat."""

from typing import Any

from thursday_main_agent.application.ports import (
    ChatRecords,
    Outbox,
    TaskProtocolRecords,
    ToolCallLogs,
    ToolServerControl,
)
from thursday_main_agent.application.runner import TaskRunner


class Deletion:
    def __init__(self, records: ChatRecords, outbox: Outbox, tools: ToolServerControl, logs: ToolCallLogs) -> None:
        self._records = records
        self._outbox = outbox
        self._tools = tools
        self._logs = logs
        self._runner: TaskRunner | None = None
        self._protocol: TaskProtocolRecords | None = None

    def attach(self, runner: TaskRunner, protocol: TaskProtocolRecords) -> None:
        """The loop's saved steps and the task protocol's records exist only once the service has started."""
        self._runner = runner
        self._protocol = protocol

    async def chat(self, chat_id: str) -> int:
        """Remove the chat's tasks, transcript, approvals, rules, saved steps and stored events, and have the tool
        server forget the chat's tool calls. Returns how many tasks it had.

        The task records go last: they name the saved steps to remove, so if a step here fails, asking again
        finds the same tasks and finishes the job."""
        task_ids = self._records.close_chat(chat_id)
        if self._runner is not None and self._protocol is not None:
            for task_id in task_ids:
                await self._runner.forget(task_id)
                await self._protocol.forget(task_id)
        self._records.delete_chat(chat_id)
        self._outbox.forget(chat_id=chat_id)
        await self._logs.forget_chat(chat_id)
        return len(task_ids)

    async def project(self, project_id: str) -> dict[str, Any]:
        """Stop the project's tool server and remove its audit log and stored events. The folder is never touched."""
        stopped = await self._tools.stop_project(project_id)
        return {
            "tool_server_stopped": stopped,
            "audit_files_removed": await self._logs.forget_project(project_id),
            "events": self._outbox.forget(project_id=project_id),
        }
