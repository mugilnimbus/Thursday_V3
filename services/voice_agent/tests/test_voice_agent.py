import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from pydantic import SecretStr
from thursday_contracts.approvals import ApprovalDecision
from thursday_llm.providers import LoadedModel
from thursday_voice_agent.bootstrap.main import VoiceAgentSettings, create_app
from thursday_voice_agent.domain.spoken import spoken_approval
from thursday_voice_agent.infrastructure.main_agent import MainAgentClient

TOKEN = "svc"
PROJECT = {"project_id": "p1", "project_folder": "C:/work"}


@pytest.mark.parametrize(
    ("text", "decision"),
    [
        ("Yes", ApprovalDecision.ALLOW_ONCE),
        ("yes, go ahead!", ApprovalDecision.ALLOW_ONCE),
        ("Allow always.", ApprovalDecision.ALLOW_ALWAYS),
        ("no", ApprovalDecision.DENY),
        ("Don't!", ApprovalDecision.DENY),
        ("yes but first tell me what it does", None),
        ("delete everything, yes", None),
        ("", None),
    ],
)
def test_only_whole_approval_phrases_count(text: str, decision: ApprovalDecision | None) -> None:
    assert spoken_approval(text) is decision


class ScriptedChat:
    def __init__(self, script: Any) -> None:
        self.script = script
        self.calls = 0

    def bind_tools(self, tools: list[dict[str, Any]]) -> "ScriptedChat":
        return self

    async def astream(self, messages: list[BaseMessage]) -> AsyncIterator[AIMessageChunk]:
        self.calls += 1
        reply: AIMessage = self.script(messages)
        chunks = [
            {"name": c["name"], "args": json.dumps(c["args"]), "id": c["id"], "index": i, "type": "tool_call_chunk"}
            for i, c in enumerate(reply.tool_calls)
        ]
        for word in str(reply.content).split(" ") if reply.content else [""]:
            yield AIMessageChunk(
                content=[{"type": "text", "text": word + " "}] if word else "",
                tool_call_chunks=cast(Any, chunks if not word or word == str(reply.content).split(" ")[-1] else []),
            )
            chunks = []


class FakeProvider:
    supports_lifecycle = False
    up = True

    async def reachable(self) -> bool:
        return self.up

    async def ensure_loaded(self) -> LoadedModel:
        return LoadedModel("voice", None, 8192, adopted=True)

    async def aclose(self) -> None: ...


class FakeMain:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error: dict[str, Any] | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append(body)
        if self.error:
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "error": self.error})
        if body["method"] == "SendMessage" and "taskId" not in body["params"]["message"]:
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {
                        "task": {"id": "task-123456789", "contextId": "c1", "status": {"state": "TASK_STATE_SUBMITTED"}}
                    },
                },
            )
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})


def delegate_then_confirm(messages: list[BaseMessage]) -> AIMessage:
    if isinstance(messages[-1], ToolMessage):
        return AIMessage("It is started.")
    return AIMessage("", tool_calls=[{"name": "delegate_task", "args": {"instruction": "Delete old.log"}, "id": "t1"}])


@pytest.fixture
def setup(tmp_path: Path) -> Iterator[tuple[TestClient, FakeMain, ScriptedChat, FakeProvider]]:
    main = FakeMain()
    chat = ScriptedChat(delegate_then_confirm)
    provider = FakeProvider()
    settings = VoiceAgentSettings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        thursday_service_token=SecretStr(TOKEN),
        gateway_localhost_port=9,
    )
    client = MainAgentClient(
        "http://main", SecretStr(TOKEN), httpx.AsyncClient(transport=httpx.MockTransport(main.handler))
    )
    app = create_app(settings, tmp_path, chat_model=chat, provider=provider, main_client=client)  # pyright: ignore[reportArgumentType]
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as http:
        yield http, main, chat, provider


def turn(http: TestClient, text: str, client_id: str) -> list[dict[str, Any]]:
    response = http.post("/v1/chats/c1/turns", json={"client_message_id": client_id, "text": text, **PROJECT})
    assert response.status_code == 200, response.text
    return [json.loads(line) for line in response.text.splitlines()]


def push(http: TestClient, token: str, state: str, parts: list[dict[str, Any]] | None = None) -> Any:
    status = {"state": state, "message": {"parts": parts or []}}
    return http.post(
        "/v1/push",
        json={"statusUpdate": {"taskId": "task-123456789", "contextId": "c1", "status": status}},
        headers={"X-A2A-Notification-Token": token},
    )


def push_token(main: FakeMain) -> str:
    first = next(c for c in main.calls if c["method"] == "SendMessage")
    return first["params"]["configuration"]["taskPushNotificationConfig"]["token"]


def test_delegation_streams_a_reply_and_sends_project_metadata(setup) -> None:
    http, main, _, _ = setup
    parts = turn(http, "please delete old.log", "m1")
    assert parts[-1] == {"type": "done", "text": "It is started."}
    assert any(p["type"] == "delta" for p in parts)
    sent = main.calls[0]["params"]
    assert sent["message"]["metadata"] == {"thursday.project_id": "p1", "thursday.project_folder": "C:/work"}
    assert sent["message"]["contextId"] == "c1" and sent["configuration"]["returnImmediately"] is True
    assert sent["configuration"]["taskPushNotificationConfig"]["url"].endswith("/v1/push")


def test_turns_are_idempotent(setup) -> None:
    http, _, chat, _ = setup
    turn(http, "please delete old.log", "m1")
    calls = chat.calls
    again = turn(http, "please delete old.log", "m1")
    assert again == [{"type": "done", "text": "It is started.", "replayed": True}] and chat.calls == calls


def test_push_needs_the_task_token_and_approval_is_answered_by_code(setup) -> None:
    http, main, chat, _ = setup
    turn(http, "please delete old.log", "m1")
    approval = {"data": {"kind": "thursday.approval_request", "approval_id": "ap-1", "summary": "Delete old.log"}}
    assert push(http, "forged", "TASK_STATE_INPUT_REQUIRED", [approval]).status_code == 401
    assert push(http, push_token(main), "TASK_STATE_INPUT_REQUIRED", [approval]).json() == {"spoken": True}
    model_calls = chat.calls
    parts = turn(http, "Yes!", "m2")
    assert parts[-1]["text"] == "Okay, allowed." and chat.calls == model_calls, "the model must not be involved"
    answer = main.calls[-1]["params"]["message"]
    assert answer["taskId"] == "task-123456789" and answer["parts"][0]["data"] == {
        "kind": "thursday.approval_answer",
        "approval_id": "ap-1",
        "decision": "allow_once",
    }
    assert answer["metadata"]["thursday.answered_by"] == "voice"


def test_yes_without_a_pending_approval_goes_to_the_model(setup) -> None:
    http, main, chat, _ = setup
    chat.script = lambda messages: AIMessage("Yes to what?")
    assert turn(http, "yes", "m1")[-1]["text"] == "Yes to what?"
    assert not any("taskId" in c["params"].get("message", {}) for c in main.calls)


def test_already_resolved_approval_is_reported_kindly(setup) -> None:
    http, main, _, _ = setup
    turn(http, "please delete old.log", "m1")
    approval = {"data": {"approval_id": "ap-1", "summary": "Delete old.log"}}
    push(http, push_token(main), "TASK_STATE_INPUT_REQUIRED", [approval])
    main.error = {"code": -32041, "message": "approval already resolved"}
    assert turn(http, "no", "m2")[-1]["text"] == "That request was already answered."


def test_completion_push_becomes_a_spoken_message_once(setup) -> None:
    http, main, _, _ = setup
    turn(http, "please delete old.log", "m1")
    token = push_token(main)
    assert push(http, token, "TASK_STATE_COMPLETED", [{"text": "Deleted old.log."}]).json() == {"spoken": True}
    assert push(http, token, "TASK_STATE_COMPLETED", [{"text": "Deleted old.log."}]).json() == {"spoken": False}
    events = http.get("/v1/replay").json()["events"]
    spoken = [e["payload"]["text"] for e in events if e["type"] == "assistant_message" and e["payload"].get("spoken")]
    assert spoken == ["Done. Deleted old.log."]


def test_voice_model_down_is_a_503_so_the_gateway_queues(setup) -> None:
    http, _, _, provider = setup
    provider.up = False
    response = http.post("/v1/chats/c1/turns", json={"client_message_id": "m9", "text": "hello", **PROJECT})
    assert response.status_code == 503


def test_turn_api_needs_the_service_token(setup) -> None:
    http, _, _, _ = setup
    response = http.post(
        "/v1/chats/c1/turns",
        json={"client_message_id": "m1", "text": "x", **PROJECT},
        headers={"Authorization": "Bearer nope"},
    )
    assert response.status_code == 401
