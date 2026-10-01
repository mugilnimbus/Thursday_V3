import json
import secrets
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
from thursday_gateway.application.control import TaskControl
from thursday_gateway.application.deletion import DeletionSaga
from thursday_gateway.application.hub import Hub
from thursday_gateway.application.projects import ProjectService
from thursday_gateway.application.relay import MessageRelay
from thursday_gateway.application.status import DependencyStatus
from thursday_gateway.bootstrap.main import GatewaySettings, create_local_app, create_proxy_app
from thursday_gateway.domain.model import Chat, Project
from thursday_gateway.infrastructure.agents import MainAgentClient, VoiceAgentClient
from thursday_gateway.infrastructure.store import Store
from thursday_gateway.infrastructure.tailnet import TailnetAddress
from thursday_gateway.transport.api import Services
from thursday_gateway.transport.device_auth import token_hash
from thursday_gateway.transport.devices_api import pairing_uri

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
        return httpx.Response(200, json=routes.get(request.url.path, {"rules": []}))

    def voice(self, request: httpx.Request) -> httpx.Response:
        if not self.voice_up:
            raise httpx.ConnectError("down")
        if request.method == "DELETE":
            self.deleted.append("voice:" + request.url.path.rsplit("/", 1)[-1])
            return httpx.Response(204)
        if request.url.path == "/ready":
            return httpx.Response(200, json={"ready": True})
        if request.url.path.startswith("/v1/llm") or request.url.path.startswith("/v1/prompt"):
            self.management.append((request.method, request.url.path, request.content.decode() or None))
            return httpx.Response(200, json={"provider": "lmstudio", "model": "m/voice"})
        body = json.loads(request.content)
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
def services(tmp_path: Path, agents: FakeAgents) -> Services:
    store = Store(tmp_path / "gateway.sqlite")
    hub = Hub()
    main = MainAgentClient(
        "http://main", SecretStr(TOKEN), httpx.AsyncClient(transport=httpx.MockTransport(agents.main))
    )
    voice = VoiceAgentClient(
        "http://voice", SecretStr(TOKEN), httpx.AsyncClient(transport=httpx.MockTransport(agents.voice))
    )
    projects = ProjectService(store)
    relay = MessageRelay(store, projects, voice, hub)
    store.add_project(Project("p1", "Seeded", str(tmp_path), datetime.now(UTC)))
    store.add_chat(Chat("c1", "p1", "Seeded chat", datetime.now(UTC)))
    return Services(
        store,
        projects,
        relay,
        TaskControl(store, main),
        DeletionSaga(store, main, voice),
        DependencyStatus(store, main, voice, relay, hub),
        main,
        hub,
        voice=voice,
    )


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
    local: TestClient, services: Services, agents: FakeAgents, tmp_path: Path
) -> None:
    import anyio

    _, chat_id = make_chat(local, tmp_path)
    ingest(local, event(1, "task_state", {"state": "completed"}, chat_id=chat_id))
    agents.voice_up = False
    assert local.delete(f"/v1/chats/{chat_id}").status_code == 202
    assert anyio.run(services.deletion.step) == 1
    assert services.store.chat(chat_id) is not None
    agents.voice_up = True
    assert anyio.run(services.deletion.step) == 0
    assert services.store.chat(chat_id) is None
    assert services.store.query("select * from events where chat_id = ?", (chat_id,)) == []
    # Deletes are idempotent, so the background saga loop may repeat the main agent's delete.
    assert agents.deleted.count(f"voice:{chat_id}") == 1 and agents.deleted.count(f"main:{chat_id}") >= 2


def test_deleting_leaves_nothing_behind_and_late_events_do_not_come_back(
    local: TestClient, services: Services, agents: FakeAgents, tmp_path: Path
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
    for chat in services.store.query("select chat_id from chats where project_id = ?", (project_id,)):
        services.projects.mark_chat_deleting(chat["chat_id"])
    import asyncio

    for _ in range(3):
        asyncio.run(services.deletion.step())
    assert any(c["method"] == "CancelTask" for c in agents.rpc_calls), "a running task is stopped first"
    assert ("DELETE", f"/v1/projects/{project_id}", None) in agents.management, "the main agent drops the project too"
    for table in ("events", "tasks", "messages", "approvals", "notifications", "outgoing"):
        left = services.store.query(f"select count(*) as n from {table} where chat_id = ?", (chat_id,))[0]["n"]
        assert left == 0, table
    assert services.store.query("select count(*) as n from events where project_id = ?", (project_id,))[0]["n"] == 0
    assert services.store.project(project_id) is None

    late = ingest(local, {**event(5, "task_state", {"state": "canceled"}), **about, "project_id": project_id}).json()
    assert late["accepted"] == 0 and late["last_seq"]["main"] == 5, "handled, so the sender moves on, but not stored"
    assert local.get("/v1/tasks/t-del").status_code == 404


def test_rows_left_by_older_versions_are_removed_at_start(services: Services) -> None:
    with services.store.tx() as db:
        db.execute(
            "insert into tasks (task_id, chat_id, project_id, state, pause_state, created_at, updated_at) "
            "values ('ghost', 'gone-chat', 'gone-project', 'completed', 'none', 'x', 'x')"
        )
        db.execute(
            "insert into messages (chat_id, role, text, pos, created_at) values ('gone-chat', 'user', 'hi', 1, 'x')"
        )
        db.execute("insert into messages (chat_id, role, text, pos, created_at) values ('c1', 'user', 'keep', 2, 'x')")
    assert services.store.purge_orphans() == 2
    assert [m["text"] for m in services.store.query("select text from messages")] == ["keep"]


def test_proxy_listener_requires_a_device_token(services: Services) -> None:
    with TestClient(create_proxy_app(services)) as proxy:
        assert proxy.get("/v1/projects").status_code == 401
        assert proxy.get("/v1/projects", headers={"Authorization": "Bearer " + "x" * 40}).status_code == 401
        assert proxy.post("/v1/events", json={"events": []}).status_code == 404, "ingest is localhost-only"
        token = secrets.token_urlsafe(32)
        with services.store.tx() as db:
            db.execute(
                "insert into devices (device_id, name, token_hash, created_at) values (?,?,?,?)",
                ("d1", "phone", token_hash(token), "now"),
            )
        assert proxy.get("/v1/projects", headers={"Authorization": f"Bearer {token}"}).status_code == 200
        with services.store.tx() as db:
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


def test_general_settings_combine_main_behavior_and_gateway_retention(local: TestClient, agents: FakeAgents) -> None:
    general = local.get("/v1/settings/general").json()
    assert general["compaction_threshold_percent"] == 90.0 and general["trace_retention_days"] == 30
    local.put("/v1/settings/general", json={"keep_awake_paused_minutes": 10, "trace_retention_days": 14})
    assert ("PUT", "/v1/behavior", '{"keep_awake_paused_minutes":10.0}') in agents.management
    assert local.get("/v1/settings/general").json()["trace_retention_days"] == 14
    assert local.put("/v1/settings/general", json={"trace_retention_days": 0}).status_code == 422


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
    from thursday_gateway.transport.api import install_error_handlers
    from thursday_gateway.transport.device_auth import trusted_local
    from thursday_gateway.transport.speech_api import SpeechClient, build_speech_router

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
        assert c.post("/v1/speech/transcribe", content=b"abcd").json()["text"] == "4 bytes"
        assert c.post("/v1/speech/transcribe", content=b"").status_code == 422
        spoken = c.post("/v1/speech/speak", json={"text": "hello"})
        assert spoken.content == b"RIFFwav" and spoken.headers["content-type"] == "audio/wav"
        assert c.post("/v1/speech/speak", json={"text": "bad"}).status_code == 422
        state["up"] = False
        assert c.get("/v1/speech").json()["available"] is False
        assert c.post("/v1/speech/speak", json={"text": "hello"}).status_code == 503


async def test_tailnet_address_prefers_the_configured_url() -> None:
    assert await TailnetAddress(" https://pc.example.ts.net/ ").url() == "https://pc.example.ts.net"
    assert pairing_uri("https://pc.ts.net", "ABCD2345") == "thursday://pair?url=https%3A%2F%2Fpc.ts.net&code=ABCD2345"
