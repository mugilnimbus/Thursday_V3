"""A task the voice agent handed to the main agent, as the voice agent remembers it."""

import uuid
from dataclasses import dataclass

TERMINAL = ("completed", "failed", "canceled", "rejected")
_REQUESTS = uuid.UUID("6f0c1f0e-6f0b-4f43-9d0a-7b4e3a5d9c21")  # any fixed value: it only keeps these names apart


def request_name(chat_id: str, client_message_id: str, ordinal: int = 0) -> str:
    """The name under which the main agent is asked to start a task: the same every time for the same message of
    the user (and, when one message starts several tasks, for the same position among them). A request whose
    answer was lost is sent again under its name, and the main agent gives back the task it already started."""
    return str(uuid.uuid5(_REQUESTS, f"{chat_id}/{client_message_id}/{ordinal}"))


@dataclass(slots=True)
class DelegatedTask:
    task_id: str
    chat_id: str
    project_id: str
    instruction: str
    state: str
    summary: str
    push_token: str
    approval_id: str | None
    approval_summary: str | None
    direct: bool = False  # the user sent it straight to the main agent, so the voice model only reports on it

    @property
    def open(self) -> bool:
        return self.state not in TERMINAL
