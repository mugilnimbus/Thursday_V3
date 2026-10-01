"""Gateway-owned records: projects, chats, queued outgoing messages."""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

MAX_NAME = 200
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class InvalidInput(ValueError):
    pass


class RecordState(StrEnum):
    ACTIVE = "active"
    DELETING = "deleting"


class OutgoingStatus(StrEnum):
    QUEUED = "queued"
    DELIVERED = "delivered"
    FAILED = "failed"


def clean_name(value: str, what: str) -> str:
    name = " ".join(value.split())
    if not name or len(name) > MAX_NAME:
        raise InvalidInput(f"{what} must be 1 to {MAX_NAME} characters")
    return name


def valid_id(value: str) -> bool:
    return bool(_ID.match(value))


@dataclass(slots=True)
class Project:
    project_id: str
    name: str
    folder: str
    created_at: datetime
    state: RecordState = RecordState.ACTIVE


@dataclass(slots=True)
class Chat:
    chat_id: str
    project_id: str
    title: str
    created_at: datetime
    state: RecordState = RecordState.ACTIVE


@dataclass(slots=True)
class Outgoing:
    """A user message the gateway accepted; delivered to the voice agent in order, retried while it is down."""

    id: int
    chat_id: str
    client_message_id: str
    text: str
    status: OutgoingStatus
    created_at: datetime
    attempts: int = 0
    error: str = ""
