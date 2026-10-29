import json
import secrets
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient
from pydantic import SecretStr
from thursday_gateway.bootstrap.main import GatewaySettings, assemble, create_local_app, create_proxy_app
from thursday_gateway.domain.model import Chat, OutgoingStatus, Project, RecordState
from thursday_gateway.infrastructure.agents import MainAgentClient, VoiceAgentClient
from thursday_gateway.infrastructure.store import Store
from thursday_gateway.infrastructure.tailnet import TailnetAddress
from thursday_gateway.transport.device_auth import token_hash
from thursday_gateway.transport.devices_api import pairing_uri
from thursday_gateway.transport.services import Services

TOKEN = "svc-token"
HOST = {"host": "127.0.0.1:8700"}  # the test client sends Host: testserver on sockets


class FakeAgents:
    """Programmable main and voice agents behind httpx mock transports."""

    def __init__(self) -> None:
        self.voice_up = True
        self.main_up = True
        self.rpc_calls: list[dict[str, Any]] = []
        self.rpc_error: dict[str, Any] | None = None
        self.deleted: list[str] = []
        self.management: list[tuple[str, str, str | None]] = []
        self.refuse_reload = False
        self.model_busy = False
        self.direct_calls: list[dict[str, Any]] = []
        self.turn_calls = 0
        self.direct_status = 200

    def main(self, request: httpx.Request) -> httpx.Response:
        if not self.main_up:
            raise httpx.ConnectError("down")
        if request.url.path == "/a2a":
            body = json.loads(request.content)
            self.rpc_calls.append(
                {"method": body["method"], "params": body["params"], "headers": dict(request.headers)}
            )
            if self.rpc_error:
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "error": self.rpc_error})
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"ok": True}})
        if request.method == "DELETE" and request.url.path.startswith("/v1/chats/"):
            self.deleted.append("main:" + request.url.path.rsplit("/", 1)[-1])
            return httpx.Response(200, json={})
        if request.url.path == "/ready":
            return httpx.Response(200, json={"ready": True, "checks": {"llm_endpoint": {"ok": True}}})
        self.management.append((request.method, request.url.path, request.content.decode() or None))
        routes = {
            "/v1/llm": {"provider": "lmstudio", "model": "m/main", "api_key_set": True},
            "/v1/behavior": {"compaction_threshold_percent": 90.0, "keep_awake_paused_minutes": 30.0},
            "/v1/allow-rules": {
                "rules": [{"chat_id": "c-known", "tool": "shell", "created_at": "2026-10-01T00:00:00"}]
            },
            "/v1/status": {"tool_servers": {}},
            "/v1/tools/catalog": {"tools": [{"name": "fs.delete", "description": "Delete", "asks_first": True}]},
        }
        if request.url.path == "/v1/model/reload" and self.refuse_reload:
            return httpx.Response(503, json={"detail": "not enough memory"})
        if (
            self.model_busy
            and request.method in ("PUT", "POST")
            and request.url.path.startswith(("/v1/llm", "/v1/model"))
        ):
            return httpx.Response(
                409, json={"detail": "The model is in use right now. Try again when it has finished."}
            )
        return httpx.Response(200, json=routes.get(request.url.path, {"rules": []}))

    def voice(self, request: httpx.Request) -> httpx.Response:
        if not self.voice_up:
            raise httpx.ConnectError("down")
        if request.method == "DELETE":
            self.deleted.append("voice:" + request.url.path.rsplit("/", 1)[-1])
            return httpx.Response(204)
        if request.url.path == "/ready":
            return httpx.Response(200, json={"ready": True})
        if request.url.path.startswith(("/v1/llm", "/v1/prompt", "/v1/retention")):
            self.management.append((request.method, request.url.path, request.content.decode() or None))
            return httpx.Response(200, json={"provider": "lmstudio", "model": "m/voice"})
        body = json.loads(request.content)
        if request.url.path.endswith("/direct"):
            self.direct_calls.append(body)
            if self.direct_status != 200:
                return httpx.Response(self.direct_status, json={"detail": "the main agent refused the task: nope"})
            return httpx.Response(200, json={"task_id": "t-new"})
        self.turn_calls += 1
        lines = [
            {"type": "delta", "text": "On "},
            {"type": "delta", "text": "it."},
            {"type": "done", "text": f"On it: {body['text']}"},
        ]
        return httpx.Response(200, content="\n".join(json.dumps(x) for x in lines).encode())


@pytest.fixture
def agents() -> FakeAgents:
    return FakeAgents()


@pytest.fixture
def store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "gateway.sqlite")
    store.add_project(Project("p1", "Seeded", str(tmp_path), datetime.now(UTC)))
    store.add_chat(Chat("c1", "p1", "Seeded chat", datetime.now(UTC)))
    return store


@pytest.fixture
def services(store: Store, agents: FakeAgents) -> Services:
    main = MainAgentClient(
        "http://main", SecretStr(TOKEN), httpx.AsyncClient(transport=httpx.MockTransport(agents.main))
    )
    voice = VoiceAgentClient(
        "http://voice", SecretStr(TOKEN), httpx.AsyncClient(transport=httpx.MockTransport(agents.voice))
    )
    return assemble(store, main, voice, retention_defaults={"data_retention_days": 30, "metrics_retention_days": 7})


@pytest.fixture
def local(services: Services) -> Iterator[TestClient]:
    settings = GatewaySettings(_env_file=None, thursday_service_token=SecretStr(TOKEN))  # pyright: ignore[reportCallIssue]
    with TestClient(
        create_local_app(services, settings), base_url="http://127.0.0.1:8700", headers={"X-Thursday-Client": "test"}
    ) as client:
        yield client


def event(
    seq: int,
    type_: str,
    payload: dict[str, Any],
    chat_id: str | None = "c1",
    task_id: str | None = "t1",
    source: str = "main",
) -> dict[str, Any]:
    return {
        "event_id": str(uuid.uuid4()),
        "source": source,
        "seq": seq,
        "ts": datetime.now(UTC).isoformat(),
        "project_id": "p1",
        "chat_id": chat_id,
        "task_id": task_id,
        "type": type_,
        "payload": payload,
    }


def ingest(client: TestClient, *events: dict[str, Any], token: str = TOKEN) -> Any:
    return client.post("/v1/events", json={"events": list(events)}, headers={"Authorization": f"Bearer {token}"})


def make_chat(client: TestClient, tmp_path: Path) -> tuple[str, str]:
    project = client.post("/v1/projects", json={"name": "Demo", "folder": str(tmp_path)}).json()
    chat = client.post(f"/v1/projects/{project['project_id']}/chats", json={"title": "First"}).json()
    return project["project_id"], chat["chat_id"]


def test_ingest_requires_the_service_token(local: TestClient) -> None:
    assert ingest(local, event(1, "task_state", {"state": "working"}), token="wrong").status_code == 401


def test_ingest_deduplicates_and_projects(local: TestClient) -> None:
    expires = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    approval = {
        "kind": "thursday.approval_request",
        "approval_id": "ap-1",
        "task_id": "t1",
        "chat_id": "c1",
        "tool": "shell",
        "summary": "Run dir",
        "arguments": {"command": "dir"},
        "expires_at": expires,
    }
    batch = [
        event(1, "delegation", {"instruction": "list files"}),
        event(2, "task_state", {"state": "working"}),
        event(3, "approval_requested", approval),
    ]
    first = ingest(local, *batch).json()
    again = ingest(local, *batch).json()
    assert (first["accepted"], again["accepted"], again["duplicates"]) == (3, 0, 3)
    assert first["last_seq"] == {"main": 3}
    task = local.get("/v1/tasks/t1").json()
    assert task["task"]["instruction"] == "list files" and task["task"]["state"] == "working"
    assert [a["approval_id"] for a in local.get("/v1/approvals").json()["approvals"]] == ["ap-1"]
    notes = local.get("/v1/notifications").json()["notifications"]
    assert notes[0]["kind"] == "approval" and "Run dir" in notes[0]["body"], "gateway notifies without the voice agent"
    ingest(local, event(4, "approval_resolved", {"approval_id": "ap-1", "outcome": "allowed"}))
    assert local.get("/v1/approvals").json()["approvals"] == []


def test_invalid_batch_is_a_problem_response(local: TestClient) -> None:
    response = local.post(
        "/v1/events", content=b'{"events": [{"nope": 1}]}', headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 422 and response.json()["code"] == "invalid_input"


def test_clients_are_told_when_projects_or_chats_change(local: TestClient, tmp_path: Path) -> None:
    with local.websocket_connect("/v1/stream", headers=HOST) as ws:
        project_id, _ = make_chat(local, tmp_path)
        assert [ws.receive_json()["kind"], ws.receive_json()["kind"]] == ["catalog_changed", "catalog_changed"]
        (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
        listed = local.get(f"/v1/projects/{project_id}/files").json()["entries"]
        assert "notes.txt" in [e["name"] for e in listed]
        assert local.get(f"/v1/projects/{project_id}/file", params={"path": "notes.txt"}).json()["text"] == "hello"
        assert local.get(f"/v1/projects/{project_id}/file", params={"path": "../x"}).status_code == 422
        assert local.get("/v1/fs/folders", params={"path": str(tmp_path.parent)}).status_code == 200


def test_project_folder_must_exist(local: TestClient, tmp_path: Path) -> None:
    bad = local.post("/v1/projects", json={"name": "X", "folder": str(tmp_path / "missing")})
    assert bad.status_code == 422 and bad.headers["content-type"].startswith("application/problem+json")


def test_websocket_replays_after_cursor_then_streams_live(local: TestClient) -> None:
    ingest(local, event(1, "task_state", {"state": "working"}), event(2, "tool_call", {"tool": "fs.read"}))
    assert local.get("/v1/status").json()["stream_pos"] == 2, "clients join the stream at the newest position"
    with local.websocket_connect("/v1/stream?after=1", headers=HOST) as ws:
        replayed = ws.receive_json()
        assert replayed["pos"] == 2 and replayed["kind"] == "timeline_event"
        ingest(local, event(3, "notification", {"title": "Done", "body": "ok", "kind": "completed"}))
        live = ws.receive_json()
        assert live["kind"] == "notification" and live["pos"] == 3


def test_message_is_relayed_and_voice_down_queues_it(
    local: TestClient, services: Services, agents: FakeAgents, tmp_path: Path
) -> None:
    _, chat_id = make_chat(local, tmp_path)
    agents.voice_up = False
    accepted = local.post(f"/v1/chats/{chat_id}/messages", json={"client_message_id": "m1", "text": "hello"})
    assert accepted.status_code == 202 and accepted.json()["status"] == "queued"
    again = local.post(f"/v1/chats/{chat_id}/messages", json={"client_message_id": "m1", "text": "hello"})
    assert again.json()["new"] is False, "idempotent on client_message_id"
    import anyio

    with pytest.raises(Exception):  # noqa: B017 - AgentUnavailable while the voice agent is down
        anyio.run(services.relay.deliver_one)
    assert local.get(f"/v1/chats/{chat_id}/messages").json()["pending"][0]["status"] == "queued"
    agents.voice_up = True
    assert anyio.run(services.relay.deliver_one) is True
    assert local.get(f"/v1/chats/{chat_id}/messages").json()["pending"] == []


def test_deleting_a_chat_fails_its_waiting_messages_and_takes_no_new_ones(
    local: TestClient, services: Services, store: Store, agents: FakeAgents, tmp_path: Path
) -> None:
    import anyio

    _, chat_id = make_chat(local, tmp_path)
    agents.voice_up = False  # the message waits, and the delete cannot finish yet
    local.post(f"/v1/chats/{chat_id}/messages", json={"client_message_id": "m1", "text": "do the work"})
    assert local.delete(f"/v1/chats/{chat_id}").status_code == 202
    waiting = store.query("select status, error from outgoing where chat_id = ?", (chat_id,))
    assert [(r["status"], r["error"]) for r in waiting] == [("failed", "The chat was deleted.")]
    more = local.post(f"/v1/chats/{chat_id}/messages", json={"client_message_id": "m2", "text": "and this"})
    assert more.status_code == 404, "a chat that is being deleted takes no new messages"
    agents.voice_up = True
    assert anyio.run(services.relay.deliver_one) is False, "nothing is left to send"
    assert agents.turn_calls == 0 and agents.direct_calls == []


def test_the_relay_sends_nothing_into_a_chat_that_is_being_deleted(
    services: Services, store: Store, agents: FakeAgents
) -> None:
    import anyio

    out, _ = store.enqueue("c1", "m1", "do the work", direct=True)
    chat = store.chat("c1")
    assert chat is not None
    chat.state = RecordState.DELETING  # marked without its messages being failed, as an older version did
    store.save_chat(chat)
    assert anyio.run(services.relay.deliver_one) is True, "the message is dealt with"
    assert agents.direct_calls == [] and agents.turn_calls == 0, "but not sent"
    row = store.query("select status, error from outgoing where id = ?", (out.id,))[0]
    assert (row["status"], row["error"]) == ("failed", "The chat was deleted.")


def test_approval_answer_goes_to_the_main_agent_and_conflicts_map_to_409(local: TestClient, agents: FakeAgents) -> None:
    expires = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    ingest(
        local,
        event(
            1,
            "approval_requested",
            {
                "approval_id": "ap-9",
                "task_id": "t9",
                "chat_id": "c1",
                "tool": "fs.delete",
                "summary": "Delete x",
                "arguments": {},
                "expires_at": expires,
            },
            task_id="t9",
        ),
    )
    assert local.post("/v1/approvals/ap-9", json={"decision": "allow_once"}).status_code == 200
    sent = agents.rpc_calls[-1]
    part = sent["params"]["message"]["parts"][0]["data"]
    assert sent["method"] == "SendMessage" and part == {
        "kind": "thursday.approval_answer",
        "approval_id": "ap-9",
        "decision": "allow_once",
    }
    assert sent["headers"]["a2a-version"] == "1.0" and sent["params"]["message"]["taskId"] == "t9"
    agents.rpc_error = {"code": -32041, "message": "approval already resolved"}
    late = local.post("/v1/approvals/ap-9", json={"decision": "deny"})
    assert late.status_code == 409 and late.json()["code"] == "approval_already_resolved"
    assert local.post("/v1/approvals/nope", json={"decision": "deny"}).status_code == 404


def test_task_control_uses_the_extension_and_reports_a_down_agent(local: TestClient, agents: FakeAgents) -> None:
    ingest(local, event(1, "task_state", {"state": "working"}))
    assert local.post("/v1/tasks/t1/pause").status_code == 200
    assert agents.rpc_calls[-1]["method"] == "PauseTask"
    assert "task-control" in agents.rpc_calls[-1]["headers"]["a2a-extensions"]
    local.post("/v1/tasks/t1/stop")
    assert agents.rpc_calls[-1]["method"] == "CancelTask"
    agents.main_up = False
    down = local.post("/v1/tasks/t1/resume")
    assert down.status_code == 503 and down.json()["code"] == "dependency_down"


def test_delete_saga_retries_until_every_service_confirms(
    local: TestClient, services: Services, store: Store, agents: FakeAgents, tmp_path: Path
) -> None:
    import anyio

    _, chat_id = make_chat(local, tmp_path)
    ingest(local, event(1, "task_state", {"state": "completed"}, chat_id=chat_id))
    agents.voice_up = False
    assert local.delete(f"/v1/chats/{chat_id}").status_code == 202
    assert anyio.run(services.deletion.step) == 1
    assert store.chat(chat_id) is not None
    agents.voice_up = True
    assert anyio.run(services.deletion.step) == 0
    assert store.chat(chat_id) is None
    assert store.query("select * from events where chat_id = ?", (chat_id,)) == []
    # Deletes are idempotent, so the background saga loop may repeat the main agent's delete.
    assert agents.deleted.count(f"voice:{chat_id}") == 1 and agents.deleted.count(f"main:{chat_id}") >= 2


def test_deleting_leaves_nothing_behind_and_late_events_do_not_come_back(
    local: TestClient, services: Services, store: Store, agents: FakeAgents, tmp_path: Path
) -> None:
    project_id, chat_id = make_chat(local, tmp_path)
    about = {"chat_id": chat_id, "task_id": "t-del"}
    ingest(
        local,
        {**event(1, "delegation", {"instruction": "do it"}), **about, "project_id": project_id},
        {**event(2, "task_state", {"state": "working"}), **about, "project_id": project_id},
        {**event(3, "user_message", {"text": "hello"}, source="voice"), "chat_id": chat_id, "task_id": None},
        {**event(4, "model_load", {"model": "m"}), "chat_id": None, "task_id": None, "project_id": project_id},
    )
    assert local.delete(f"/v1/projects/{project_id}").status_code == 202
    for chat in store.query("select chat_id from chats where project_id = ?", (project_id,)):
        services.projects.mark_chat_deleting(chat["chat_id"])
    import asyncio

    for _ in range(3):
        asyncio.run(services.deletion.step())
    assert any(c["method"] == "CancelTask" for c in agents.rpc_calls), "a running task is stopped first"
    assert ("DELETE", f"/v1/projects/{project_id}", None) in agents.management, "the main agent drops the project too"
    for table in ("events", "tasks", "messages", "approvals", "notifications", "outgoing"):
        left = store.query(f"select count(*) as n from {table} where chat_id = ?", (chat_id,))[0]["n"]
        assert left == 0, table
    assert store.query("select count(*) as n from events where project_id = ?", (project_id,))[0]["n"] == 0
    assert store.project(project_id) is None

    late = ingest(local, {**event(5, "task_state", {"state": "canceled"}), **about, "project_id": project_id}).json()
    assert late["accepted"] == 0 and late["last_seq"]["main"] == 5, "handled, so the sender moves on, but not stored"
    assert local.get("/v1/tasks/t-del").status_code == 404


def test_rows_left_by_older_versions_are_removed_at_start(services: Services, store: Store) -> None:
    with store.tx() as db:
        db.execute(
            "insert into tasks (task_id, chat_id, project_id, state, pause_state, created_at, updated_at) "
            "values ('ghost', 'gone-chat', 'gone-project', 'completed', 'none', 'x', 'x')"
        )
        db.execute(
            "insert into messages (chat_id, role, text, pos, created_at) values ('gone-chat', 'user', 'hi', 1, 'x')"
        )
        db.execute("insert into messages (chat_id, role, text, pos, created_at) values ('c1', 'user', 'keep', 2, 'x')")
    assert services.retention.remove_orphans() == 2
    assert [m["text"] for m in store.query("select text from messages")] == ["keep"]


def test_proxy_listener_requires_a_device_token(services: Services, store: Store) -> None:
    with TestClient(create_proxy_app(services)) as proxy:
        assert proxy.get("/v1/projects").status_code == 401
        assert proxy.get("/v1/projects", headers={"Authorization": "Bearer " + "x" * 40}).status_code == 401
        assert proxy.post("/v1/events", json={"events": []}).status_code == 404, "ingest is localhost-only"
        token = secrets.token_urlsafe(32)
        with store.tx() as db:
            db.execute(
                "insert into devices (device_id, name, token_hash, created_at) values (?,?,?,?)",
                ("d1", "phone", token_hash(token), "now"),
            )
        assert proxy.get("/v1/projects", headers={"Authorization": f"Bearer {token}"}).status_code == 200
        with store.tx() as db:
            db.execute("update devices set revoked = 1")
        assert proxy.get("/v1/projects", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_pairing_code_is_made_on_the_pc_and_works_once(services: Services, local: TestClient) -> None:
    with TestClient(create_proxy_app(services)) as proxy:
        assert proxy.post("/v1/devices/pairing").status_code in (401, 404, 405), "codes are localhost-only"
        made = local.post("/v1/devices/pairing").json()
        assert len(made["code"]) == 9 and made["code"][4] == "-"
        assert proxy.post("/v1/devices/claim", json={"code": "ZZZZ-ZZZZ", "name": "Phone"}).status_code == 422
        claimed = proxy.post("/v1/devices/claim", json={"code": made["code"].lower(), "name": " Pixel  9 "})
        assert claimed.status_code == 201
        token = claimed.json()["token"]
        again = proxy.post("/v1/devices/claim", json={"code": made["code"], "name": "Other"})
        assert again.status_code == 422, "a code works once"
        auth = {"Authorization": f"Bearer {token}"}
        listed = proxy.get("/v1/devices", headers=auth).json()["devices"]
        assert [d["name"] for d in listed] == ["Pixel 9"] and listed[0]["last_seen"]
        assert "token" not in json.dumps(listed) and "hash" not in json.dumps(listed)
        with proxy.websocket_connect("/v1/stream", headers=auth) as ws:
            assert local.delete(f"/v1/devices/{listed[0]['device_id']}").status_code == 204
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
            assert closed.value.code == 1008, "a revoked phone is disconnected at once"
        assert proxy.get("/v1/projects", headers=auth).status_code == 401


def test_pairing_claims_are_rate_limited(services: Services, local: TestClient) -> None:
    local.post("/v1/devices/pairing")
    codes = [local.post("/v1/devices/claim", json={"code": "WRONG-CODE", "name": "x"}).status_code for _ in range(6)]
    assert codes == [422] * 5 + [429]


def test_search_finds_chat_messages(local: TestClient, tmp_path: Path) -> None:
    _, chat_id = make_chat(local, tmp_path)
    ingest(
        local,
        event(
            1,
            "user_message",
            {"text": "please rename the report", "client_message_id": "m1"},
            chat_id=chat_id,
            source="voice",
        ),
    )
    hits = local.get("/v1/search", params={"q": "rename"}).json()["results"]
    assert hits[0]["chat_id"] == chat_id and hits[0]["role"] == "user"


def test_metrics_ingest_monitor_and_live_stream(services: Services, tmp_path: Path) -> None:
    from thursday_gateway.infrastructure.metrics_store import MetricsStore

    services.metrics = MetricsStore(tmp_path / "metrics.sqlite")
    settings = GatewaySettings(_env_file=None, thursday_service_token=SecretStr(TOKEN))  # pyright: ignore[reportCallIssue]
    sample = {
        "ts": datetime.now(UTC).isoformat(),
        "cpu_percent": 10.0,
        "ram_used_mb": 1,
        "ram_total_mb": 2,
        "net_rx_bytes_per_s": 0.0,
        "net_tx_bytes_per_s": 0.0,
        "gpus": [],
        "services": [],
    }
    with TestClient(
        create_local_app(services, settings), base_url="http://127.0.0.1:8700", headers={"X-Thursday-Client": "test"}
    ) as client:
        assert client.post("/v1/metrics", json=sample).status_code == 401
        with client.websocket_connect("/v1/metrics/stream", headers=HOST) as ws:
            posted = client.post("/v1/metrics", json=sample, headers={"Authorization": f"Bearer {TOKEN}"})
            assert posted.status_code == 204
            assert ws.receive_json()["sample"]["cpu_percent"] == 10.0
        second = {**sample, "ts": (datetime.now(UTC) + timedelta(seconds=1)).isoformat(), "cpu_percent": 20.0}
        client.post("/v1/metrics", json=second, headers={"Authorization": f"Bearer {TOKEN}"})
        monitor = client.get("/v1/monitor", params={"range": "1h"}).json()
        assert monitor["latest"]["cpu_percent"] == 20.0, "live values every second"
        assert len(monitor["history"]) == 1, "history is written at most every 5 seconds"
        assert client.get("/v1/monitor", params={"range": "1y"}).status_code == 422
        usage = {"input_tokens": 900, "output_tokens": 30}
        ingest(
            client, event(1, "llm_call", {"agent": "main", "status": "ok", "tokens_per_second": 80.5, "usage": usage})
        )
        ingest(client, event(2, "llm_call", {"agent": "main", "status": "error: Timeout"}))
        calls = client.get("/v1/monitor", params={"range": "1h"}).json()["llm_calls"]
        assert [(c["agent"], c["tokens_per_second"], c["input_tokens"]) for c in calls] == [("main", 80.5, 900)]
        assert client.get("/metrics").json()["pending_approvals"] == 0


def test_agent_settings_are_forwarded_to_the_right_agent(local: TestClient, agents: FakeAgents) -> None:
    assert local.get("/v1/agents/main/llm").json()["model"] == "m/main"
    assert local.get("/v1/agents/voice/llm").json()["model"] == "m/voice"
    local.put("/v1/agents/voice/llm", json={"model": "m/other"})
    assert agents.management[-1] == ("PUT", "/v1/llm", '{"model":"m/other"}')
    local.post("/v1/agents/main/model/reload", json={"context_length": 16384})
    assert agents.management[-1][:2] == ("POST", "/v1/model/reload")
    agents.refuse_reload = True
    refused = local.post("/v1/agents/main/model/reload")
    assert refused.status_code == 503 and "not enough memory" in refused.json()["detail"]
    assert local.get("/v1/agents/nobody/llm").status_code == 404


def test_a_change_refused_because_the_model_is_in_use_reaches_the_client_with_the_reason(
    local: TestClient, agents: FakeAgents
) -> None:
    agents.model_busy = True
    for refused in (
        local.put("/v1/agents/main/llm", json={"inference": {"temperature": 0.2}}),
        local.post("/v1/agents/main/model/unload"),
    ):
        assert refused.status_code == 409
        assert refused.json()["detail"] == "The model is in use right now. Try again when it has finished."
    agents.model_busy = False
    assert local.put("/v1/agents/main/llm", json={"inference": {"temperature": 0.2}}).status_code == 200


def test_general_settings_combine_main_behavior_and_gateway_retention(local: TestClient, agents: FakeAgents) -> None:
    general = local.get("/v1/settings/general").json()
    assert general["compaction_threshold_percent"] == 90.0 and general["data_retention_days"] == 30
    assert general["trace_retention_days"] == 30, "the older name is still answered"
    local.put("/v1/settings/general", json={"keep_awake_paused_minutes": 10, "trace_retention_days": 14})
    assert ("PUT", "/v1/behavior", '{"keep_awake_paused_minutes":10.0}') in agents.management
    assert local.get("/v1/settings/general").json()["trace_retention_days"] == 14
    assert local.put("/v1/settings/general", json={"trace_retention_days": 0}).status_code == 422


def test_the_working_data_period_is_one_setting_and_zero_keeps_everything(
    local: TestClient, services: Services, store: Store, agents: FakeAgents
) -> None:
    def told(days: int) -> int:
        return agents.management.count(("PUT", "/v1/retention", f'{{"days":{days}}}'))

    assert told(30) == 2, "at start both agents are told the period in force"
    changed = local.put("/v1/settings/general", json={"data_retention_days": 90})
    assert changed.status_code == 200 and changed.json()["data_retention_days"] == 90
    assert told(90) == 2, "a change reaches both agents at once"
    assert local.put("/v1/settings/general", json={"data_retention_days": 4000}).status_code == 422

    ingest(local, event(1, "task_state", {"state": "working"}))
    with store.tx() as db:
        db.execute("update events set received_at = '2020-01-01T00:00:00+00:00'")
    assert local.put("/v1/settings/general", json={"data_retention_days": 0}).json()["data_retention_days"] == 0
    assert services.retention.prune() == 0, "0 keeps working data until it is deleted by hand"
    local.put("/v1/settings/general", json={"data_retention_days": 7})
    assert services.retention.prune() == 1 and store.query("select 1 from events") == []
    assert store.query("select count(*) as n from tasks")[0]["n"] == 1, "the task list is never removed by age"


async def test_a_service_that_was_down_is_told_the_period_when_it_is_back_and_nobody_twice(store: Store) -> None:
    from thursday_gateway.application.errors import AgentUnavailable
    from thursday_gateway.application.retention import Retention

    class Target:
        def __init__(self) -> None:
            self.up = True
            self.heard: list[int] = []

        async def set_retention(self, days: int) -> None:
            if not self.up:
                raise AgentUnavailable("down")
            self.heard.append(days)

    main, voice = Target(), Target()
    defaults = {"data_retention_days": 30, "metrics_retention_days": 7}
    retention = Retention(store, store, None, defaults, {"main agent": main, "voice agent": voice})
    assert await retention.sync() == ["main agent", "voice agent"] and await retention.sync() == []
    voice.up = False
    retention.change({"data_retention_days": 90})
    assert await retention.sync() == ["main agent"]
    voice.up = True
    assert await retention.sync() == ["voice agent"] and await retention.sync() == []
    assert main.heard == [30, 90] and voice.heard == [30, 90]


def test_a_period_saved_under_the_older_name_still_counts(store: Store) -> None:
    from thursday_gateway.application.retention import Retention

    store.set_setting("retention", {"trace_retention_days": 14, "metrics_retention_days": 3})
    retention = Retention(store, store, None, {"data_retention_days": 30, "metrics_retention_days": 7})
    assert retention.current() == {"data_retention_days": 14, "metrics_retention_days": 3}


def test_trace_list_filters_and_tools_join_chat_titles(local: TestClient, tmp_path: Path) -> None:
    _, chat_id = make_chat(local, tmp_path)
    ingest(
        local,
        event(1, "delegation", {"instruction": "tidy logs"}, chat_id=chat_id, task_id="t-a"),
        event(2, "task_state", {"state": "failed"}, chat_id=chat_id, task_id="t-b"),
    )
    assert [t["task_id"] for t in local.get("/v1/tasks", params={"state": "failed"}).json()["tasks"]] == ["t-b"]
    found = local.get("/v1/tasks", params={"q": "tidy"}).json()["tasks"]
    assert found[0]["chat_title"] == "First"
    tools = local.get("/v1/tools").json()
    assert tools["rules"][0]["chat_title"] == "Deleted chat" and tools["catalog"][0]["asks_first"]
    assert tools["servers"][0]["alive"] is False


def test_local_listener_blocks_rebinding_cross_site_and_headerless_writes(services: Services) -> None:
    settings = GatewaySettings(_env_file=None, thursday_service_token=SecretStr(TOKEN))  # pyright: ignore[reportCallIssue]
    app = create_local_app(services, settings)
    with TestClient(app, base_url="http://evil.example:8700") as rebinding:
        assert rebinding.get("/v1/projects").status_code == 403
    with TestClient(app, base_url="http://127.0.0.1:8700") as browser:
        assert browser.get("/v1/projects").status_code == 200, "reads from this PC are fine"
        blocked = browser.post("/v1/backup")
        assert blocked.status_code == 403 and blocked.json()["detail"] == "missing client header"
        cross = browser.post("/v1/backup", headers={"X-Thursday-Client": "x", "Origin": "https://evil.example"})
        assert cross.status_code == 403 and cross.json()["detail"] == "cross-origin request"
        evil = {**HOST, "Origin": "https://evil.example"}
        with pytest.raises(Exception), browser.websocket_connect("/v1/stream", headers=evil) as ws:  # noqa: B017
            ws.receive_json()
        ingest_ok = browser.post("/v1/events", json={"events": []}, headers={"Authorization": f"Bearer {TOKEN}"})
        assert ingest_ok.status_code == 422, "agents use the service token and need no client header"


def test_speech_routes_forward_audio_and_report_a_down_service() -> None:
    from fastapi import FastAPI
    from thursday_gateway.infrastructure.speech_client import SpeechClient
    from thursday_gateway.transport.device_auth import trusted_local
    from thursday_gateway.transport.errors import install_error_handlers
    from thursday_gateway.transport.speech_api import build_speech_router

    state = {"up": True}

    def speech(request: httpx.Request) -> httpx.Response:
        if not state["up"]:
            raise httpx.ConnectError("down")
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        if request.url.path == "/v1/transcribe":
            return httpx.Response(200, json={"text": f"{len(request.content)} bytes", "language": "en"})
        if request.url.path == "/v1/speak":
            if json.loads(request.content)["text"] == "bad":
                return httpx.Response(422, json={"detail": "unknown voice"})
            return httpx.Response(200, content=b"RIFFwav", headers={"content-type": "audio/wav"})
        return httpx.Response(200, json={"voices": ["af_heart"]})

    client = SpeechClient("http://speech", SecretStr(TOKEN), httpx.AsyncClient(transport=httpx.MockTransport(speech)))
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(build_speech_router(client, trusted_local))
    with TestClient(app) as c:
        assert c.get("/v1/speech").json() == {"available": True, "voices": ["af_heart"]}
        heard = c.post("/v1/speech/transcribe", content=b"abcd").json()
        assert heard["text"] == "4 bytes" and heard["by"] == "whisper", "no voice agent given: speech-to-text"
        assert c.post("/v1/speech/transcribe", content=b"").status_code == 422
        spoken = c.post("/v1/speech/speak", json={"text": "hello"})
        assert spoken.content == b"RIFFwav" and spoken.headers["content-type"] == "audio/wav"
        assert c.post("/v1/speech/speak", json={"text": "bad"}).status_code == 422
        state["up"] = False
        assert c.get("/v1/speech").json()["available"] is False
        assert c.post("/v1/speech/speak", json={"text": "hello"}).status_code == 503


def test_a_recording_is_heard_by_the_voice_model_first_and_by_speech_to_text_when_it_cannot() -> None:
    from fastapi import FastAPI
    from thursday_gateway.infrastructure.speech_client import SpeechClient
    from thursday_gateway.transport.device_auth import trusted_local
    from thursday_gateway.transport.errors import install_error_handlers
    from thursday_gateway.transport.speech_api import build_speech_router

    calls: list[str] = []
    state: dict = {"hears": {"text": "open the notes", "by": "voice_model"}, "decode": 200}

    def speech(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/v1/decode":
            return httpx.Response(state["decode"], content=b"RIFFwav:" + request.content)
        return httpx.Response(200, json={"text": "whisper heard it", "language": "en"})

    class Voice:
        def __init__(self) -> None:
            self.heard: list[bytes] = []

        async def hear(self, wav: bytes) -> dict | None:
            self.heard.append(wav)
            return state["hears"]

    voice = Voice()
    client = SpeechClient("http://speech", SecretStr(TOKEN), httpx.AsyncClient(transport=httpx.MockTransport(speech)))
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(build_speech_router(client, trusted_local, voice))
    with TestClient(app) as c:
        assert c.post("/v1/speech/transcribe", content=b"webm").json() == {
            "text": "open the notes",
            "by": "voice_model",
        }
        assert calls == ["/v1/decode"] and voice.heard == [b"RIFFwav:webm"], "the model gets WAV; Whisper is not used"

        state["hears"] = None  # the model cannot hear, is too slow, or is down
        calls.clear()
        assert c.post("/v1/speech/transcribe", content=b"webm").json() == {
            "text": "whisper heard it",
            "language": "en",
            "by": "whisper",
        }
        assert calls == ["/v1/decode", "/v1/transcribe"]

        state["decode"] = 422  # a recording that cannot be decoded still goes to speech-to-text, which reports it
        calls.clear()
        assert c.post("/v1/speech/transcribe", content=b"webm").json()["by"] == "whisper"
        assert calls == ["/v1/decode", "/v1/transcribe"] and len(voice.heard) == 2


async def test_tailnet_address_prefers_the_configured_url() -> None:
    assert await TailnetAddress(" https://pc.example.ts.net/ ").url() == "https://pc.example.ts.net"
    assert pairing_uri("https://pc.ts.net", "ABCD2345") == "thursday://pair?url=https%3A%2F%2Fpc.ts.net&code=ABCD2345"


# --- direct mode: a chat can send its messages straight to the main agent ------------------------
def set_direct(client: TestClient, chat_id: str, direct: bool) -> Any:
    return client.patch(f"/v1/chats/{chat_id}", json={"direct": direct})


def pending_of(client: TestClient, chat_id: str) -> list[dict[str, Any]]:
    return client.get(f"/v1/chats/{chat_id}/messages").json()["pending"]


def wait_until(check: Any, timeout: float = 10.0) -> None:
    """The gateway's relay loop delivers in the background, so tests wait for its result."""
    deadline = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < deadline, "timed out waiting for the relay"
        time.sleep(0.05)


def test_the_direct_switch_belongs_to_the_chat_and_every_client_is_told(local: TestClient, tmp_path: Path) -> None:
    project_id, chat_id = make_chat(local, tmp_path)
    assert local.get(f"/v1/projects/{project_id}/chats").json()["chats"][0]["direct"] is False
    with local.websocket_connect("/v1/stream", headers=HOST) as ws:
        flipped = set_direct(local, chat_id, True)
        assert flipped.json() == {"chat_id": chat_id, "title": "First", "direct": True}
        assert ws.receive_json()["kind"] == "catalog_changed"
    assert local.get(f"/v1/projects/{project_id}/chats").json()["chats"][0]["direct"] is True
    renamed = local.patch(f"/v1/chats/{chat_id}", json={"title": "Second"}).json()
    assert renamed["title"] == "Second" and renamed["direct"] is True, "renaming leaves the switch alone"
    assert set_direct(local, chat_id, False).json()["direct"] is False
    assert set_direct(local, "nope", True).status_code == 404


def test_messages_in_a_direct_chat_go_straight_to_the_main_agent(
    local: TestClient, agents: FakeAgents, tmp_path: Path
) -> None:
    project_id, chat_id = make_chat(local, tmp_path)
    set_direct(local, chat_id, True)
    agents.voice_up = False  # keep it queued long enough to look at
    words = "  Delete   old.log\nthen list the rest  "
    accepted = local.post(f"/v1/chats/{chat_id}/messages", json={"client_message_id": "m1", "text": words})
    assert accepted.json() == {"status": "queued", "new": True, "direct": True}
    assert pending_of(local, chat_id)[0]["direct"] is True
    agents.voice_up = True
    wait_until(lambda: pending_of(local, chat_id) == [])
    assert agents.turn_calls == 0, "the voice model's turn is skipped"
    assert agents.direct_calls == [
        {"client_message_id": "m1", "text": words, "project_id": project_id, "project_folder": str(tmp_path)}
    ]


def test_the_switch_is_read_when_the_message_is_accepted_not_when_it_is_delivered(
    local: TestClient, agents: FakeAgents, tmp_path: Path
) -> None:
    _, chat_id = make_chat(local, tmp_path)
    agents.voice_up = False
    set_direct(local, chat_id, True)
    local.post(f"/v1/chats/{chat_id}/messages", json={"client_message_id": "m1", "text": "first"})
    set_direct(local, chat_id, False)
    local.post(f"/v1/chats/{chat_id}/messages", json={"client_message_id": "m2", "text": "second"})
    agents.voice_up = True
    wait_until(lambda: pending_of(local, chat_id) == [])
    assert [c["text"] for c in agents.direct_calls] == ["first"] and agents.turn_calls == 1


def test_a_direct_message_waits_while_the_agents_are_down_and_fails_with_the_reason_when_refused(
    local: TestClient, agents: FakeAgents, tmp_path: Path
) -> None:
    _, chat_id = make_chat(local, tmp_path)
    set_direct(local, chat_id, True)
    agents.voice_up = False
    local.post(f"/v1/chats/{chat_id}/messages", json={"client_message_id": "m1", "text": "go"})
    time.sleep(0.3)
    assert pending_of(local, chat_id)[0]["status"] == "queued"
    agents.voice_up = True
    agents.direct_status = 503  # the voice agent is up but the main agent is not
    time.sleep(1.5)
    assert pending_of(local, chat_id)[0]["status"] == "queued", "kept for later, not lost"
    agents.direct_status = 409
    wait_until(lambda: pending_of(local, chat_id)[0]["status"] == "failed")
    assert "refused the task" in pending_of(local, chat_id)[0]["error"]


def test_direct_user_messages_are_marked_in_the_stored_chat(local: TestClient, tmp_path: Path) -> None:
    _, chat_id = make_chat(local, tmp_path)
    ingest(
        local,
        event(1, "user_message", {"text": "do it", "client_message_id": "a", "direct": True}, chat_id, None, "voice"),
        event(2, "user_message", {"text": "hello", "client_message_id": "b"}, chat_id, None, "voice"),
        event(3, "assistant_message", {"text": "Done."}, chat_id, None, "voice"),
    )
    rows = local.get(f"/v1/chats/{chat_id}/messages").json()["messages"]
    assert [(r["role"], r["direct"]) for r in rows] == [("user", True), ("user", False), ("assistant", False)]


def test_a_user_message_published_again_after_a_stop_is_shown_once_and_kept_in_the_log(
    local: TestClient, tmp_path: Path
) -> None:
    _, chat_id = make_chat(local, tmp_path)
    ingest(
        local,
        event(1, "user_message", {"text": "hello", "client_message_id": "a"}, chat_id, None, "voice"),
        event(2, "user_message", {"text": "hello", "client_message_id": "a"}, chat_id, None, "voice"),
        event(3, "assistant_message", {"text": "Hi."}, chat_id, None, "voice"),
        event(4, "user_message", {"text": "hello", "client_message_id": "b"}, chat_id, None, "voice"),
    )
    rows = local.get(f"/v1/chats/{chat_id}/messages").json()["messages"]
    assert [(r["role"], r["client_message_id"]) for r in rows] == [("user", "a"), ("assistant", None), ("user", "b")]
    timeline = local.get(f"/v1/chats/{chat_id}/timeline").json()["events"]
    assert [e["event"]["type"] for e in timeline].count("user_message") == 3, "the event log keeps every event"


def test_a_message_cut_off_by_a_stopped_voice_agent_is_sent_again_after_its_late_user_message_event(
    local: TestClient, agents: FakeAgents, tmp_path: Path
) -> None:
    _, chat_id = make_chat(local, tmp_path)
    agents.voice_up = False  # the turn was cut off: the relay keeps the message queued
    local.post(f"/v1/chats/{chat_id}/messages", json={"client_message_id": "m1", "text": "hello"})
    time.sleep(0.3)
    # the restarted agent's outbox now delivers the user_message it published before it was stopped
    ingest(local, event(1, "user_message", {"text": "hello", "client_message_id": "m1"}, chat_id, None, "voice"))
    assert [p["status"] for p in pending_of(local, chat_id)] == ["queued"], "not answered, so still queued"
    agents.voice_up = True
    wait_until(lambda: pending_of(local, chat_id) == [])
    assert agents.turn_calls == 1


def test_a_database_from_before_direct_mode_is_upgraded_in_place(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "old.sqlite"
    db = sqlite3.connect(path)
    db.executescript(
        "create table schema_version (version integer not null); insert into schema_version values (1);"
        "create table chats (chat_id text primary key, project_id text not null, title text not null,"
        " created_at text not null, state text not null, last_activity text not null);"
        "insert into chats values ('c9', 'p9', 'Old chat', '2026-09-01T00:00:00+00:00', 'active', 'x');"
        "create table outgoing (id integer primary key autoincrement, chat_id text not null,"
        " client_message_id text not null, text text not null, status text not null, created_at text not null,"
        " attempts integer not null default 0, error text not null default '', unique (chat_id, client_message_id));"
        "create table messages (id integer primary key autoincrement, chat_id text not null, role text not null,"
        " text text not null, client_message_id text, pos integer not null, created_at text not null);"
    )
    db.close()
    store = Store(path)
    chat = store.chat("c9")
    assert chat is not None and chat.direct is False and chat.title == "Old chat"
    chat.direct = True
    store.save_chat(chat)
    reopened = Store(path)  # opening it again must not try to add the columns twice
    assert (reopened.chat("c9") or chat).direct is True
    out, _ = reopened.enqueue("c9", "m1", "hi", direct=True)
    assert out.direct is True


async def test_pressing_the_microphone_loads_what_the_turn_will_need() -> None:
    from thursday_gateway.application.errors import AgentUnavailable
    from thursday_gateway.application.talk_warmup import TalkWarmup

    class Reply:
        status_code = 200

        def __init__(self, body: dict[str, Any]) -> None:
            self._body = body

        def json(self) -> dict[str, Any]:
            return self._body

    class Speech:
        def __init__(self) -> None:
            self.calls: list[dict[str, bool]] = []

        async def call(self, method: str, path: str, **kwargs: Any) -> Any:
            assert (method, path) == ("POST", "/warm")
            self.calls.append(kwargs["json"])
            return Reply({})

    class Voice:
        def __init__(self, hears: bool, up: bool = True) -> None:
            self.hears, self.up, self.loads = hears, up, 0

        async def request(self, method: str, path: str, **kwargs: Any) -> Any:
            assert (method, path) == ("POST", "/model/load")
            if not self.up:
                raise AgentUnavailable("down")
            self.loads += 1
            return Reply({"hears_audio": self.hears})

    speech, voice = Speech(), Voice(hears=False)
    await TalkWarmup(speech, voice).run(speak=True)  # pyright: ignore[reportArgumentType]
    assert voice.loads == 1, "the voice model starts loading while the person is still talking"
    assert speech.calls == [{"listen": False, "speak": True}, {"listen": True, "speak": False}]

    speech, voice = Speech(), Voice(hears=True)
    await TalkWarmup(speech, voice).run(speak=False)  # pyright: ignore[reportArgumentType]
    assert speech.calls == [], "a model that hears needs no speech-to-text, and nothing is read aloud"

    speech = Speech()
    await TalkWarmup(speech, Voice(hears=False, up=False)).run(speak=False)  # pyright: ignore[reportArgumentType]
    assert speech.calls == [{"listen": True, "speak": False}], "a voice agent that is down does not stop the rest"

    speech, voice = Speech(), Voice(hears=False)
    await TalkWarmup(speech, voice).run(speak=True, listen=False)  # pyright: ignore[reportArgumentType]
    assert (voice.loads, speech.calls) == (0, [{"listen": False, "speak": True}]), "a typed message warms the voice"


async def test_one_missed_check_does_not_call_an_agent_down() -> None:
    from thursday_gateway.application.status import DependencyStatus

    class Agent:
        def __init__(self, answers: list[dict[str, Any] | None]) -> None:
            self.answers = list(answers)

        async def ready(self) -> dict[str, Any] | None:
            return self.answers.pop(0)

    class Records:
        def queued_count(self) -> int:
            return 0

        def last_seq(self) -> dict[str, int]:
            return {}

    ok: dict[str, Any] = {"checks": {"llm_endpoint": {"ok": True}}}
    voice = Agent([ok, None, ok, None, None, ok])
    status = DependencyStatus(Records(), Agent([ok] * 6), voice, None, None)  # pyright: ignore[reportArgumentType]
    seen = [(await status.check())["voice_agent"] for _ in range(6)]
    assert seen == [True, True, True, True, False, True], "down from the second miss in a row, up again at once"

    never = DependencyStatus(Records(), Agent([ok]), Agent([None]), None, None)  # pyright: ignore[reportArgumentType]
    first = await never.check()
    assert first["voice_agent"] is False, "an agent that has never answered has no last answer to stand on"
    assert [b["code"] for b in first["banners"]] == ["voice_agent_down"]


async def test_a_readiness_check_on_a_connection_the_agent_just_closed_is_asked_again() -> None:
    import httpx
    from pydantic import SecretStr
    from thursday_gateway.infrastructure.agents import VoiceAgentClient

    def agent(*outcomes: object) -> VoiceAgentClient:
        left = list(outcomes)

        def answer(request: httpx.Request) -> httpx.Response:
            outcome = left.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return httpx.Response(200, json=outcome)

        return VoiceAgentClient(
            "http://voice", SecretStr("t"), httpx.AsyncClient(transport=httpx.MockTransport(answer))
        )

    dropped = httpx.RemoteProtocolError("Server disconnected without sending a response.")
    assert await agent(dropped, {"ready": True}).ready() == {"ready": True}, "asked once more on a new connection"
    assert await agent(dropped, dropped).ready() is None, "dropped twice: that is a miss"
    assert await agent(httpx.ReadTimeout("slow"), {"ready": True}).ready() is None, "a slow agent is not asked twice"
    assert await agent(httpx.ConnectError("refused")).ready() is None


def test_sending_a_failed_message_again_queues_it_again(
    local: TestClient, services: Services, store: Store, agents: FakeAgents, tmp_path: Path
) -> None:
    _, chat_id = make_chat(local, tmp_path)
    out, _ = store.enqueue(chat_id, "m1", "hello")
    store.set_outgoing(out.id, OutgoingStatus.FAILED, "the voice agent refused it")
    again = local.post(f"/v1/chats/{chat_id}/messages", json={"client_message_id": "m1", "text": "hello"})
    assert again.status_code == 202 and (again.json()["status"], again.json()["new"]) == ("queued", True)

    def status() -> str:
        return store.query("select status from outgoing where id = ?", (out.id,))[0]["status"]

    wait_until(lambda: status() == "delivered")  # the relay's own loop sends it; a second sender here would race it
    assert agents.turn_calls == 1, "it was sent this time, once"
    once_more = local.post(f"/v1/chats/{chat_id}/messages", json={"client_message_id": "m1", "text": "hello"})
    assert once_more.json()["new"] is False, "a delivered message is not sent twice"


def test_search_finds_a_windows_path_as_typed(local: TestClient, tmp_path: Path) -> None:
    _, chat_id = make_chat(local, tmp_path)
    texts = [r"open C:\work\100%_done\notes.txt", "open C:/work/100 done", r"a share at \\server\files"]
    for n, text in enumerate(texts, start=1):
        ingest(
            local,
            event(n, "user_message", {"text": text, "client_message_id": f"m{n}"}, chat_id=chat_id, source="voice"),
        )

    def found(q: str) -> list[str]:
        return [h["text"] for h in local.get("/v1/search", params={"q": q}).json()["results"]]

    assert found(r"C:\work") == [texts[0]]
    assert found("100%_done") == [texts[0]], "% and _ stand for themselves"
    assert found(r"work\100%_done\ ".strip()) == [texts[0]], "a backslash at the end too"
    assert found("\\\\server") == [texts[2]]


def test_a_very_long_task_trace_keeps_its_start_and_its_end(store: Store, services: Services) -> None:
    with store.tx() as db:
        db.executemany(
            "insert into events (source, seq, event_id, type, ts, task_id, payload, received_at) "
            "values (?,?,?,?,?,?,?,?)",
            [("main", n, f"e{n}", "task_status", "t", "t1", "{}", "t") for n in range(1, 26)],
        )
    events, omitted = services.read.task_events("t1", limit=10)
    assert [e["seq"] for e in events] == [1, 2, 3, 4, 5, 21, 22, 23, 24, 25] and omitted == 15
    events, omitted = services.read.task_events("t1", limit=25)
    assert len(events) == 25 and omitted == 0


def test_a_chat_holds_at_most_100_waiting_messages(local: TestClient, tmp_path: Path, store: Store) -> None:
    _, chat_id = make_chat(local, tmp_path)
    for n in range(100):
        store.enqueue(chat_id, f"m{n}", "hello")
    refused = local.post(f"/v1/chats/{chat_id}/messages", json={"client_message_id": "extra", "text": "one too many"})
    assert (
        refused.status_code == 429
        and refused.json()["code"] == "rate_limited"
        and refused.headers["Retry-After"] == "30"
    )
    again = local.post(f"/v1/chats/{chat_id}/messages", json={"client_message_id": "m0", "text": "hello"})
    assert again.status_code == 202 and again.json()["new"] is False, "a message already waiting is not refused again"
    _, other = make_chat(local, tmp_path)
    assert local.post(f"/v1/chats/{other}/messages", json={"client_message_id": "x", "text": "hi"}).status_code == 202
