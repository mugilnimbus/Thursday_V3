"""What this service reports about itself: to the gateway's Tools screen, and to the metrics collector."""

from typing import Any

from thursday_main_agent.application.keep_awake import KeepAwake
from thursday_main_agent.application.ports import GatewayLink, OpenWork, Outbox, ToolServerControl
from thursday_main_agent.application.runner import TaskRunner
from thursday_main_agent.application.tasks import TaskService


class ServiceStatus:
    def __init__(
        self, work: OpenWork, outbox: Outbox, gateway: GatewayLink, tools: ToolServerControl, keep_awake: KeepAwake
    ) -> None:
        self._work = work
        self._outbox = outbox
        self._gateway = gateway
        self._tools = tools
        self._keep_awake = keep_awake
        self._tasks: TaskService | None = None
        self._runner: TaskRunner | None = None

    def attach(self, tasks: TaskService, runner: TaskRunner) -> None:
        """The task service and the loop exist only once the service has started."""
        self._tasks = tasks
        self._runner = runner

    def status(self) -> dict[str, Any]:
        return {
            "running_tasks": sorted(self._tasks.running) if self._tasks else [],
            "tool_servers": self._tools.status(),
            "gateway_reachable": self._gateway.gateway_reachable,
            "outbox_backlog": self._outbox.backlog(),
        }

    def metrics(self) -> dict[str, Any]:
        return {
            "running_tasks": len(self._tasks.running) if self._tasks else 0,
            "open_tasks": len(self._work.open_tasks()),
            "pending_approvals": len(self._work.pending_approvals()),
            "outbox_backlog": self._outbox.backlog(),
            "tool_servers_alive": sum(1 for s in self._tools.status().values() if s["alive"]),
            "gateway_reachable": self._gateway.gateway_reachable,
            "keeping_awake": self._keep_awake.active,
            **(self._runner.last_llm if self._runner else {}),
        }
