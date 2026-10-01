import json
from pathlib import Path

from thursday_runtime.outbox import OutboxStore


def add(outbox: OutboxStore, chat_id: str | None, project_id: str | None) -> int:
    return outbox.add(lambda seq: json.dumps({"seq": seq, "chat_id": chat_id, "project_id": project_id}))


def test_forgetting_a_chat_removes_its_events_sent_or_not(tmp_path: Path) -> None:
    outbox = OutboxStore(tmp_path / "outbox.sqlite")
    first = add(outbox, "c-gone", "p1")
    add(outbox, "c-keep", "p1")
    add(outbox, "c-gone", "p1")
    outbox.mark_sent(first)
    assert outbox.forget(chat_id="c-gone") == 2
    assert [e["chat_id"] for e in outbox.after(0, 10)] == ["c-keep"], "a replay cannot bring the chat back"
    assert outbox.backlog() == 1


def test_forgetting_a_project_removes_its_events_only(tmp_path: Path) -> None:
    outbox = OutboxStore(tmp_path / "outbox.sqlite")
    add(outbox, None, "p-gone")
    add(outbox, "c1", "p-keep")
    add(outbox, None, None)
    assert outbox.forget(project_id="p-gone") == 1
    assert len(outbox.after(0, 10)) == 2
    assert outbox.forget() == 0, "nothing named, nothing removed"
