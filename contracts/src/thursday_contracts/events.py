"""Event envelope sent by every service to the gateway (`POST /v1/events`).

Delivery is at least once from each service's outbox. The gateway deduplicates by
`event_id` and orders per `source` by `seq`.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = 1
MAX_BATCH_EVENTS = 500


class EventSource(StrEnum):
    VOICE = "voice"
    MAIN = "main"
    COLLECTOR = "collector"
    TOOL = "tool"


class EventType(StrEnum):
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    DELEGATION = "delegation"
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RESOLVED = "approval_resolved"
    TASK_STATE = "task_state"
    COMPACTION = "compaction"
    MODEL_LOAD = "model_load"
    NOTIFICATION = "notification"
    ERROR = "error"


class EventEnvelope(BaseModel):
    """One event. `project_id` and `chat_id` are absent only for global events such as a model load."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=64)
    schema_version: int = SCHEMA_VERSION
    source: EventSource
    seq: int = Field(ge=1, description="Per-source counter, strictly increasing, for ordering and gap detection.")
    ts: datetime
    project_id: str | None = None
    chat_id: str | None = None
    task_id: str | None = None
    type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ts")
    @classmethod
    def _require_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("ts must be timezone-aware")
        return value.astimezone(UTC)


class EventBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[EventEnvelope] = Field(min_length=1, max_length=MAX_BATCH_EVENTS)


class IngestResult(BaseModel):
    """Gateway reply to a batch. `last_seq` is the highest contiguous seq stored for the source."""

    accepted: int
    duplicates: int
    last_seq: dict[EventSource, int] = Field(default_factory=dict)
