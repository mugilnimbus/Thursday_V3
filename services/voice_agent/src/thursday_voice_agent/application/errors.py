"""What the voice agent's logic is told when work cannot go ahead: the main agent cannot do what was asked, or
the chat was deleted.

The client in `infrastructure` raises the main agent's; the logic and the HTTP layer handle them all.
"""


class ChatDeleted(Exception):
    """The chat this work is for was deleted. Nothing is started or written for it."""


class MainAgentUnavailable(Exception):
    """The main agent could not be reached."""


class MainAgentRefused(Exception):
    """The main agent answered, and the answer was no. `code` is its HTTP status or JSON-RPC error code."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
