"""What the gateway's logic is told when another service cannot do what was asked.

The clients in `infrastructure` raise these; the logic and the HTTP layer handle them.
"""


class AgentUnavailable(Exception):
    """The service could not be reached."""


class AgentRefused(Exception):
    """The service answered, and the answer was no. `code` is its HTTP status or JSON-RPC error code."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
