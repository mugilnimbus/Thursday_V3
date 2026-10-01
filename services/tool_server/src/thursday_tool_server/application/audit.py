"""Port for the call and permission audit log (implemented in infrastructure)."""

from typing import Any, Protocol


class CallAudit(Protocol):
    def start(self, tool: str, arguments: dict[str, object], permission: str) -> Any:
        """Record a call starting; returns an opaque handle for `finish`."""
        ...

    def finish(self, record: Any, outcome: str, detail: str = "") -> None: ...
