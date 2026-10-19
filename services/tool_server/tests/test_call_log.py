"""The call log: which chat a call belongs to, how long calls are kept, and forgetting a chat or a project."""

import sqlite3
import time
from pathlib import Path

import pytest
from mcp.client.client import Client
from thursday_runtime.call_meta import CHAT_ID_META_KEY
from thursday_tool_server.bootstrap.main import ToolServerSettings, build, maintain, parse
from thursday_tool_server.infrastructure.audit_log import AuditLog, forget_chat

DAY = 24 * 3600


def backdate(path: Path, call_id: int, days: float) -> None:
    db = sqlite3.connect(path, isolation_level=None)
    db.execute("update calls set started_at = ? where id = ?", (time.time() - days * DAY, call_id))
    db.close()


def test_calls_older_than_the_period_leave_and_zero_keeps_everything(tmp_path: Path) -> None:
    path = tmp_path / "proj.sqlite"
    log = AuditLog(path, keep_days=30)
    old = log.start("fs.read", {"path": "a.txt"}, "allow", "chat-a")
    log.start("fs.read", {"path": "b.txt"}, "allow", "chat-b")
    backdate(path, old.call_id, 31)
    assert log.prune() == 1
    assert [row[3] for row in log.recent()] == ["chat-b"]
    log.close()

    forever = AuditLog(path, keep_days=0)
    kept = forever.start("fs.read", {"path": "c.txt"}, "allow", "chat-c")
    backdate(path, kept.call_id, 4000)
    assert forever.prune() == 0 and len(forever.recent()) == 2, "0 keeps calls until their chat or project is deleted"
    forever.close()


def test_a_log_made_before_chats_were_recorded_is_upgraded_once(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite"
    db = sqlite3.connect(path, isolation_level=None)
    db.executescript(
        "create table schema_version (version integer not null); insert into schema_version values (1);"
        "create table calls (id integer primary key, started_at real not null, finished_at real, tool text not null,"
        " arguments text not null, permission text not null, outcome text, detail text);"
    )
    db.execute(
        "insert into calls (started_at, tool, arguments, permission) values (?, 'fs.list', '{}', 'allow')",
        (time.time(),),
    )
    db.close()
    for _ in range(2):  # opening it again must not try to add the column twice
        log = AuditLog(path, keep_days=30)
        assert log.recent() == [("fs.list", "allow", None, None)], "the old call stays, with no chat"
        log.close()
    assert sqlite3.connect(path).execute("select max(version) from schema_version").fetchone()[0] == 2


def test_forgetting_a_chat_removes_its_calls_from_every_project_and_nothing_else(tmp_path: Path) -> None:
    for project, chats in (("p1", ["chat-a", "chat-b"]), ("p2", ["chat-a"])):
        log = AuditLog(tmp_path / f"{project}.sqlite", keep_days=0)
        for chat in chats:
            log.finish(log.start("shell", {"command": "dir"}, "ask:accepted", chat), "ok")
        log.finish(log.start("fs.list", {}, "allow"), "ok")
        log.close()
    assert forget_chat(tmp_path, "chat-a") == 2
    assert forget_chat(tmp_path, "chat-a") == 0, "safe to repeat"
    left = AuditLog(tmp_path / "p1.sqlite", keep_days=0)
    assert sorted(str(row[3]) for row in left.recent()) == ["None", "chat-b"]
    left.close()


@pytest.fixture
def settings(tmp_path: Path) -> ToolServerSettings:
    return ToolServerSettings(thursday_data_dir=str(tmp_path / "data"))


async def test_the_chat_sent_beside_a_call_is_recorded_and_is_not_an_argument(layout, settings) -> None:
    server, _, audit = build(str(layout["ws"]), "proj-1", settings)
    try:
        async with Client(server.mcp) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            assert all("ctx" not in (t.input_schema.get("properties") or {}) for t in tools.values())
            await client.session.call_tool("fs.list", {"path": "."}, meta={CHAT_ID_META_KEY: "chat-7"})
            await client.session.call_tool("fs.list", {"path": "."}, meta={CHAT_ID_META_KEY: "../not an id"})
            await client.session.call_tool("fs.list", {"path": "."})
        assert [row[3] for row in audit.recent()] == [None, None, "chat-7"], "newest first"
    finally:
        audit.close()


def test_the_clean_up_commands_work_on_this_servers_own_logs(layout, settings, capsys) -> None:
    _, _, audit = build(str(layout["ws"]), "proj-1", settings)
    audit.finish(audit.start("fs.read", {"path": "notes.txt"}, "allow", "chat-9"), "ok")
    audit.close()
    assert maintain(["forget-chat", "--chat-id", "chat-9"], settings) == {"removed": 1}
    files = maintain(["forget-project", "--project-id", "proj-1"], settings)["files"]
    assert isinstance(files, list) and files[0] == "proj-1.sqlite"
    assert maintain(["forget-project", "--project-id", "proj-1"], settings) == {"files": []}
    with pytest.raises(SystemExit):
        maintain(["forget-chat", "--chat-id", "../../etc"], settings)
    capsys.readouterr()


def test_the_server_is_told_how_long_to_keep_its_log() -> None:
    assert parse(["--workspace", ".", "--project-id", "p1"]).keep_days == 30
    assert parse(["--workspace", ".", "--project-id", "p1", "--keep-days", "0"]).keep_days == 0
