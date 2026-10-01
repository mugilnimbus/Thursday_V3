from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from thursday_contracts.events import (
    MAX_BATCH_EVENTS,
    SCHEMA_VERSION,
    EventBatch,
    EventEnvelope,
    EventSource,
    EventType,
)


def make(**overrides: object) -> EventEnvelope:
    fields: dict[str, object] = {
        "source": EventSource.MAIN,
        "seq": 1,
        "ts": datetime.now(UTC),
        "project_id": "p1",
        "chat_id": "c1",
        "type": EventType.TOOL_CALL,
        "payload": {"tool": "fs.read"},
    }
    fields.update(overrides)
    return EventEnvelope.model_validate(fields)


def test_round_trip_through_json_keeps_every_field() -> None:
    event = make(task_id="t1")
    again = EventEnvelope.model_validate_json(event.model_dump_json())
    assert again == event
    assert again.schema_version == SCHEMA_VERSION


def test_event_ids_are_unique_by_default() -> None:
    assert make().event_id != make().event_id


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make(ts=datetime(2026, 9, 30, 12, 0))


def test_timestamp_is_normalised_to_utc() -> None:
    local = datetime(2026, 9, 30, 12, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert make(ts=local).ts == datetime(2026, 9, 30, 6, 30, tzinfo=UTC)


@pytest.mark.parametrize("bad", [{"seq": 0}, {"source": "gateway"}, {"type": "unknown"}, {"extra_field": 1}])
def test_invalid_envelopes_are_rejected(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        make(**bad)


def test_global_event_may_omit_project_and_chat() -> None:
    event = make(project_id=None, chat_id=None, type=EventType.MODEL_LOAD)
    assert event.chat_id is None


def test_batch_size_is_bounded() -> None:
    with pytest.raises(ValidationError):
        EventBatch(events=[])
    with pytest.raises(ValidationError):
        EventBatch(events=[make(seq=i + 1) for i in range(MAX_BATCH_EVENTS + 1)])
