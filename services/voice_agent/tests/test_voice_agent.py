import asyncio
import json
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, ToolMessage
from pydantic import SecretStr
from thursday_contracts.approvals import ApprovalDecision
from thursday_llm.providers import LoadedModel
from thursday_voice_agent.application.errors import MainAgentUnavailable
from thursday_voice_agent.application.history import trim_orphans
from thursday_voice_agent.application.tasks import TaskRelay
from thursday_voice_agent.bootstrap.main import VoiceAgentSettings, create_app
from thursday_voice_agent.domain.reports import report_problem
from thursday_voice_agent.domain.spoken import spoken_approval
from thursday_voice_agent.domain.tasks import DelegatedTask, request_name
from thursday_voice_agent.infrastructure.main_agent import MainAgentClient
from thursday_voice_agent.infrastructure.store import Store

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
        self.bound = 0  # how many times tools were offered to the model

    def bind_tools(self, tools: list[dict[str, Any]]) -> "ScriptedChat":
        self.bound += 1
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
        self.lose_answers = 0  # how many new tasks are started with the answer lost on the way back

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append(body)
        if self.error:
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "error": self.error})
        if body["method"] == "SendMessage" and "taskId" not in body["params"]["message"]:
            if self.lose_answers:
                self.lose_answers -= 1
                raise httpx.ReadTimeout("the answer was lost")
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


def project_of(sent: dict[str, Any]) -> dict[str, Any]:
    """A new task's metadata without the name of the request."""
    return {k: v for k, v in sent["message"]["metadata"].items() if k != "thursday.request"}


def new_tasks(main: FakeMain) -> list[dict[str, Any]]:
    """What was sent to start tasks, in order."""
    return [c["params"] for c in main.calls if c["method"] == "SendMessage" and "taskId" not in c["params"]["message"]]


def name_of(sent: dict[str, Any]) -> str:
    return sent["message"]["metadata"]["thursday.request"]


def push_token(main: FakeMain) -> str:
    first = next(c for c in main.calls if c["method"] == "SendMessage")
    return first["params"]["configuration"]["taskPushNotificationConfig"]["token"]


def test_delegation_streams_a_reply_and_sends_project_metadata(setup) -> None:
    http, main, _, _ = setup
    parts = turn(http, "please delete old.log", "m1")
    assert parts[-1] == {"type": "done", "text": "It is started."}
    assert any(p["type"] == "delta" for p in parts)
    sent = main.calls[0]["params"]
    assert project_of(sent) == {"thursday.project_id": "p1", "thursday.project_folder": "C:/work"}
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


# --- direct mode: the user's words go straight to the main agent --------------------------------
def direct(http: TestClient, text: str, client_id: str, chat: str = "c1") -> Any:
    return http.post(f"/v1/chats/{chat}/direct", json={"client_message_id": client_id, "text": text, **PROJECT})


def events_of(http: TestClient, kind: str) -> list[dict[str, Any]]:
    return [e for e in http.get("/v1/replay").json()["events"] if e["type"] == kind]


def spoken(http: TestClient) -> list[str]:
    return [e["payload"]["text"] for e in events_of(http, "assistant_message") if e["payload"].get("spoken")]


def wait_for_spoken(http: TestClient) -> list[str]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if said := spoken(http):
            return said
        time.sleep(0.05)
    raise AssertionError("nothing was said")


def finish(http: TestClient, main: FakeMain, text: str = "Deleted old.log.") -> None:
    assert push(http, push_token(main), "TASK_STATE_COMPLETED", [{"text": text}]).status_code == 200


def test_direct_send_starts_the_task_with_the_exact_words_and_never_asks_the_voice_model(setup) -> None:
    http, main, chat, _ = setup
    words = "  Delete   old.log, then tell me what is left.\nThanks  "
    response = direct(http, words, "d1")
    assert response.status_code == 200 and response.json() == {"task_id": "task-123456789"}
    sent = main.calls[0]["params"]
    assert sent["message"]["parts"] == [{"text": words}], "word for word, nothing trimmed or reworded"
    assert project_of(sent) == {"thursday.project_id": "p1", "thursday.project_folder": "C:/work"}
    assert chat.calls == 0, "no voice model call to send a direct message"
    kinds = [e["type"] for e in http.get("/v1/replay").json()["events"]]
    assert kinds.index("user_message") < kinds.index("delegation"), "the chat reads in order"
    assert events_of(http, "user_message")[0]["payload"] == {"text": words, "client_message_id": "d1", "direct": True}
    assert events_of(http, "delegation")[0]["payload"]["by"] == "direct"


def test_direct_send_is_idempotent(setup) -> None:
    http, main, _, _ = setup
    assert direct(http, "Delete old.log", "d1").json() == {"task_id": "task-123456789"}
    assert direct(http, "Delete old.log", "d1").json() == {"replayed": True}
    assert len([c for c in main.calls if c["method"] == "SendMessage"]) == 1


def test_a_direct_task_is_written_into_the_voice_transcript_as_a_delegation(setup) -> None:
    http, _, chat, _ = setup
    seen: list[list[BaseMessage]] = []

    def script(messages: list[BaseMessage]) -> AIMessage:
        seen.append(messages)
        return AIMessage("Okay.")

    direct(http, "Delete old.log", "d1")
    chat.script = script
    turn(http, "how is it going?", "m1")
    history = seen[0][1:-1]  # without the system prompt and the new question
    assert [m.type for m in history] == ["human", "ai", "tool"]
    assert history[0].content == "Delete old.log"
    assert history[1].tool_calls[0]["name"] == "delegate_task"  # type: ignore[attr-defined]
    assert history[1].tool_calls[0]["args"] == {"instruction": "Delete old.log"}  # type: ignore[attr-defined]
    assert "started in the background" in str(history[2].content) and "not known yet" in str(history[2].content)


def test_a_plain_yes_still_answers_a_waiting_approval_in_direct_mode(setup) -> None:
    http, main, _, _ = setup
    direct(http, "Delete old.log", "d1")
    approval = {"data": {"approval_id": "ap-1", "summary": "Delete old.log"}}
    push(http, push_token(main), "TASK_STATE_INPUT_REQUIRED", [approval])

    def starts() -> int:
        return len([c for c in main.calls if c["method"] == "SendMessage" and "taskId" not in c["params"]["message"]])

    before = starts()
    assert direct(http, "yes", "d2").json() == {"answered": "Okay, allowed."}
    assert starts() == before, "an approval answer is not a new task"
    assert main.calls[-1]["params"]["message"]["parts"][0]["data"]["decision"] == "allow_once"


def test_direct_send_says_so_when_the_main_agent_refuses_or_is_down(setup, monkeypatch: pytest.MonkeyPatch) -> None:
    http, main, _, _ = setup
    main.error = {"code": -32004, "message": "nope"}
    refused = direct(http, "Delete old.log", "d1")
    assert refused.status_code == 409 and "refused" in refused.text
    assert events_of(http, "user_message") == [] and events_of(http, "delegation") == [], "nothing half-published"

    async def unreachable(*args: Any, **kwargs: Any) -> Any:
        raise MainAgentUnavailable("ConnectError")

    monkeypatch.setattr(MainAgentClient, "start_task", unreachable)
    assert direct(http, "Delete old.log", "d2").status_code == 503


def test_the_voice_model_reports_a_finished_direct_task_with_no_tools_and_the_report_rule(setup) -> None:
    http, main, chat, _ = setup
    views: list[list[BaseMessage]] = []

    def script(messages: list[BaseMessage]) -> AIMessage:
        views.append(messages)
        return AIMessage("It deleted old.log, and nothing else is left.")

    direct(http, "Delete old.log", "d1")
    chat.script = script
    bound = chat.bound
    finish(http, main, "Deleted old.log. The folder is now empty.")
    assert wait_for_spoken(http) == ["It deleted old.log, and nothing else is left."]
    (view,) = views
    assert chat.bound == bound, "the report is asked for with no tools offered"
    assert view[0].type == "system" and "only reporting a finished task" in str(view[0].content)
    assert [m.type for m in view[1:]] == ["human", "ai", "tool"]
    assert view[1].content == "Delete old.log"
    assert view[2].tool_calls[0]["id"] == view[3].tool_call_id  # type: ignore[attr-defined]
    assert "The main agent's result: Deleted old.log. The folder is now empty." in str(view[3].content)
    assert spoken(http) == ["It deleted old.log, and nothing else is left."], "said exactly once"


def test_the_report_sees_what_was_said_before_the_message_but_not_after_it(setup) -> None:
    http, main, chat, _ = setup
    chat.script = lambda messages: AIMessage("Hello there.")
    turn(http, "hello", "m1")
    direct(http, "Delete old.log", "d1")
    chat.script = lambda messages: AIMessage("Later chat.")
    turn(http, "and another thing", "m2")
    views: list[list[BaseMessage]] = []

    def script(messages: list[BaseMessage]) -> AIMessage:
        views.append(messages)
        return AIMessage("Done and dusted.")

    chat.script = script
    finish(http, main)
    wait_for_spoken(http)
    texts = [m.text.strip() for m in views[0]]
    assert "hello" in texts and "Hello there." in texts
    assert "and another thing" not in texts and "Later chat." not in texts


@pytest.mark.parametrize(
    "reply",
    [
        "",
        "   ",
        '<|tool_call>call:delegate_task{instruction:"x"}<tool_call|>',
        "I have delegated that to the main agent.",
    ],
)
def test_an_untrustworthy_report_is_replaced_by_the_main_agents_own_words(setup, reply: str) -> None:
    http, main, chat, _ = setup
    direct(http, "Delete old.log", "d1")
    chat.script = lambda messages: AIMessage(reply)
    finish(http, main)
    assert wait_for_spoken(http) == ["Done. Deleted old.log."]


def test_the_main_agents_words_are_used_when_the_voice_model_is_down(setup) -> None:
    http, main, chat, provider = setup
    direct(http, "Delete old.log", "d1")
    provider.up = False
    finish(http, main)
    assert wait_for_spoken(http) == ["Done. Deleted old.log."] and chat.calls == 0


def test_the_main_agents_words_are_used_when_the_voice_model_breaks(setup) -> None:
    http, main, chat, _ = setup

    def broken(messages: list[BaseMessage]) -> AIMessage:
        raise RuntimeError("model fell over")

    direct(http, "Delete old.log", "d1")
    chat.script = broken
    finish(http, main)
    assert wait_for_spoken(http) == ["Done. Deleted old.log."]


def test_failed_and_stopped_direct_tasks_are_reported_by_code_not_the_model(setup) -> None:
    http, main, chat, _ = setup
    direct(http, "Delete old.log", "d1")
    failed = push(http, push_token(main), "TASK_STATE_FAILED", [{"text": "The model ran out of context."}])
    assert failed.status_code == 200
    assert wait_for_spoken(http) == ["The task failed. The model ran out of context."]
    assert chat.calls == 0


def test_a_normal_task_is_still_announced_by_code(setup) -> None:
    http, main, chat, _ = setup
    turn(http, "please delete old.log", "m1")
    calls = chat.calls
    finish(http, main)
    assert wait_for_spoken(http) == ["Done. Deleted old.log."] and chat.calls == calls


def test_direct_api_needs_the_service_token(setup) -> None:
    http, _, _, _ = setup
    response = http.post(
        "/v1/chats/c1/direct",
        json={"client_message_id": "d1", "text": "x", **PROJECT},
        headers={"Authorization": "Bearer nope"},
    )
    assert response.status_code == 401


def test_a_history_window_never_starts_with_a_tool_answer() -> None:
    orphan = ToolMessage("x", tool_call_id="gone")
    kept = [HumanMessage("hi"), AIMessage("hello")]
    assert trim_orphans([orphan, orphan, *kept]) == kept and trim_orphans(kept) == kept and trim_orphans([]) == []


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("It deleted old.log.", None),
        ("", "empty"),
        ("<|tool_call>call:x{}<tool_call|>", "tool-call syntax"),
        ("```\ncall:delegate_task{x}", "tool-call syntax"),
        ("I have delegated it.", "talks about delegating or progress, not a result"),
        ("The work is still in progress.", "talks about delegating or progress, not a result"),
        ("x" * 2000, "too long"),
    ],
)
def test_report_checks(text: str, problem: str | None) -> None:
    assert report_problem(text) == problem


def test_voice_history_is_cut_to_the_chosen_token_count_newest_first() -> None:
    from langchain_core.messages import AIMessage, HumanMessage
    from thursday_voice_agent.application.history import within_tokens

    history = [HumanMessage("a" * 350), AIMessage("b" * 350), HumanMessage("c" * 350)]  # about 100 tokens each
    assert within_tokens(history, None) == history, "no limit chosen: everything recent is kept"
    assert [m.content[0] for m in within_tokens(history, 210)] == ["b", "c"]
    assert within_tokens(history, 50) == [], "one message larger than the limit is not sent in part"


def _wav(seconds: float) -> bytes:
    import io
    import wave

    out = io.BytesIO()
    with wave.open(out, "wb") as clip:
        clip.setnchannels(1)
        clip.setsampwidth(2)
        clip.setframerate(16000)
        clip.writeframes(b"\x00\x00" * int(16000 * seconds))
    return out.getvalue()


def test_a_recording_is_written_down_by_the_voice_model_when_it_can_hear(setup) -> None:
    http, _, _, provider = setup
    assert http.post("/v1/hear", content=_wav(2)).status_code == 409, "this model cannot hear: use speech-to-text"

    heard: list[int] = []

    async def hear(wav: bytes) -> str | None:
        heard.append(len(wav))
        return provider.words

    provider.hear = hear
    provider.words = "delete the old log"
    reply = http.post("/v1/hear", content=_wav(2)).json()
    assert reply["text"] == "delete the old log" and reply["by"] == "voice_model" and reply["audio_seconds"] == 2.0
    assert len(heard) == 1

    assert http.post("/v1/hear", content=_wav(31)).status_code == 409, "too long for the model: use speech-to-text"
    assert len(heard) == 1, "a clip that is too long is never sent to the model"
    provider.words = ""
    assert http.post("/v1/hear", content=_wav(1)).status_code == 409, "nothing heard: let speech-to-text try"
    provider.words = "Hey, I am going to tell you about my trip to Italy."
    assert http.post("/v1/hear", content=_wav(0.6)).status_code == 409, "more words than fit in the clip: made up"
    provider.words = "Allow always."
    assert http.post("/v1/hear", content=_wav(0.6)).json()["text"] == "Allow always."
    provider.words = None
    assert http.post("/v1/hear", content=_wav(1)).status_code == 409
    assert http.post("/v1/hear", content=b"not a wav").status_code == 422
    assert http.post("/v1/hear", content=_wav(1), headers={"Authorization": "Bearer nope"}).status_code == 401


def test_working_data_is_kept_for_the_period_the_gateway_sends_and_chats_stay(setup, tmp_path: Path) -> None:
    import sqlite3
    from datetime import UTC, datetime, timedelta

    from thursday_voice_agent.application.retention import WorkingData
    from thursday_voice_agent.infrastructure.store import Store

    http, _, _, _ = setup
    assert http.get("/v1/retention").json() == {"days": 30}, "the value from .env until one is sent"
    assert http.put("/v1/retention", json={"days": 7}).json() == {"days": 7}
    assert http.put("/v1/retention", json={"days": 4000}).status_code == 422
    turn(http, "hello", "m1")

    long_ago = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    for name, sql in (
        ("voice_agent.sqlite", "update turns set created_at = ?"),
        ("outbox.sqlite", "update outbox set created_at = ?"),
    ):
        db = sqlite3.connect(tmp_path / name, isolation_level=None)
        db.execute(sql, (long_ago,))
        db.close()

    class Sent:
        """An outbox whose events were all delivered eight days ago."""

        def prune_sent(self, older_than: timedelta) -> int:
            return 3 if older_than <= timedelta(days=8) else 0

    store = Store(tmp_path / "voice_agent.sqlite")
    try:
        working = WorkingData(store, store, Sent(), default_days=30)  # pyright: ignore[reportArgumentType]
        assert working.days == 7, "this service keeps its own copy of the period"
        assert working.prune() == {"events": 3, "turns": 1}
        assert len(store.transcript("c1")) >= 2, "what was said stays until the chat is deleted"
        working.apply(0)
        assert working.prune() == {"events": 0, "turns": 0}, "0 keeps everything until it is deleted by hand"
    finally:
        store.close()


def test_the_window_of_recent_messages_starts_at_the_same_message_for_many_turns() -> None:
    from langchain_core.messages import AnyMessage, HumanMessage
    from thursday_voice_agent.application.history import fit_in_steps, window_start

    assert [window_start(n, 60, 20) for n in (0, 59, 60)] == [0, 0, 0], "a short chat is shown whole"
    starts = [window_start(n, 60, 20) for n in range(61, 121)]
    assert starts[0] == 20 and set(starts[:20]) == {20} and set(starts[20:40]) == {40} and set(starts[40:]) == {60}
    assert all(40 < n - window_start(n, 60, 20) <= 60 for n in range(61, 400)), "between 41 and 60 messages are shown"

    history: list[AnyMessage] = [HumanMessage(str(i).rjust(3, "0") * 100) for i in range(60)]  # 300 characters each
    assert fit_in_steps(history, None, 20) == history, "no limit chosen: everything recent is kept"
    kept = fit_in_steps(history, 3600, 20)  # room for 42 messages: whole steps of 20 are dropped
    assert len(kept) == 40 and kept[0] is history[20]
    assert fit_in_steps([*history, HumanMessage("x" * 300)], 3600, 20)[0] is history[20], (
        "the next turn starts the same"
    )
    assert len(fit_in_steps(history[:20], 100, 20)) == 1, "one step that is still too large is cut message by message"


# --- a request to start a task has a name, so one that is sent again is not a second task -------
def test_a_request_goes_by_the_same_name_every_time_and_by_another_for_another_message() -> None:
    assert request_name("c1", "m1") == request_name("c1", "m1")
    others = {request_name("c1", "m2"), request_name("c2", "m1"), request_name("c1", "m1", 1)}
    assert request_name("c1", "m1") not in others and len(others) == 3


def test_a_direct_message_whose_answer_was_lost_is_sent_again_under_the_same_name(setup) -> None:
    http, main, _, _ = setup
    main.lose_answers = 1  # the main agent starts the task, and its answer does not arrive
    assert direct(http, "Delete old.log", "d1").status_code == 503, "the gateway keeps the message and tries again"
    assert events_of(http, "delegation") == [], "nothing is announced for an answer that never came"
    assert direct(http, "Delete old.log", "d1").json() == {"task_id": "task-123456789"}
    first, again = new_tasks(main)
    assert name_of(first) == name_of(again), "so the main agent can tell it is the same request"
    assert first["message"]["messageId"] == again["message"]["messageId"] == name_of(first)

    def token(sent: dict[str, Any]) -> str:
        return sent["configuration"]["taskPushNotificationConfig"]["token"]

    assert token(first) == token(again), "the main agent keeps the first one it was given, so they have to match"
    assert len(events_of(http, "delegation")) == 1

    direct(http, "Delete old.log", "d2")
    another = new_tasks(main)[-1]
    assert name_of(another) != name_of(first), "the same words in a new message are a new request"
    assert token(another) != token(first)


def test_a_turn_that_is_run_again_asks_for_its_task_under_the_same_name(setup) -> None:
    http, main, chat, _ = setup

    def stops_after_delegating(messages: list[BaseMessage]) -> AIMessage:
        if isinstance(messages[-1], ToolMessage):
            raise RuntimeError("the model stopped")
        return delegate_then_confirm(messages)

    chat.script = stops_after_delegating
    with pytest.raises(RuntimeError):
        http.post("/v1/chats/c1/turns", json={"client_message_id": "m1", "text": "please delete old.log", **PROJECT})
    chat.script = delegate_then_confirm
    assert turn(http, "please delete old.log", "m1")[-1]["text"] == "It is started."
    first, again = new_tasks(main)
    assert name_of(first) == name_of(again) == request_name("c1", "m1")
    assert len(events_of(http, "delegation")) == 1, "and the task it gets back is not announced a second time"


def test_two_tasks_started_by_one_message_go_by_two_names(setup) -> None:
    http, main, chat, _ = setup

    def two_tasks(messages: list[BaseMessage]) -> AIMessage:
        if isinstance(messages[-1], ToolMessage):
            return AIMessage("Both are started.")
        calls = [
            {"name": "delegate_task", "args": {"instruction": "Delete old.log"}, "id": "t1"},
            {"name": "list_tasks", "args": {}, "id": "t2"},
            {"name": "delegate_task", "args": {"instruction": "Delete new.log"}, "id": "t3"},
        ]
        return AIMessage("", tool_calls=calls)

    chat.script = two_tasks
    turn(http, "delete both logs", "m1")
    assert [name_of(sent) for sent in new_tasks(main)] == [request_name("c1", "m1", 0), request_name("c1", "m1", 1)]


def test_a_task_that_is_already_known_is_not_added_twice(tmp_path: Path) -> None:
    store = Store(tmp_path / "voice.sqlite")
    task = DelegatedTask("t1", "c1", "p1", "work", "working", "", "token", None, None, True)
    store.add_task(task)
    store.update_task("t1", "completed", summary="done")
    store.add_task(task)  # the request was sent again and the main agent gave the same task back
    assert [(t.task_id, t.state, t.summary) for t in store.tasks_for_chat("c1")] == [("t1", "completed", "done")]
    store.close()


# --- a deleted chat takes no late work and no late writes ---------------------------------------
def test_a_deleted_chat_takes_no_new_message(setup) -> None:
    http, main, chat, _ = setup
    turn(http, "please delete old.log", "m1")
    started = len(new_tasks(main))
    assert http.delete("/v1/chats/c1").status_code == 204
    refused = direct(http, "Delete new.log", "d1")
    assert refused.status_code == 410 and "deleted" in refused.text, "the gateway fails the message, with the reason"
    later = http.post("/v1/chats/c1/turns", json={"client_message_id": "m2", "text": "and now?", **PROJECT})
    assert later.status_code == 410
    assert len(new_tasks(main)) == started and chat.calls == 2, "no task was started and the model was not asked"
    assert direct(http, "Delete old.log", "d1", chat="c2").status_code == 200, "other chats are not affected"


def test_nothing_is_stored_or_sent_out_for_a_chat_after_it_was_deleted(setup, tmp_path: Path) -> None:
    http, main, _, _ = setup
    direct(http, "Delete old.log", "d1")
    token = push_token(main)
    assert http.delete("/v1/chats/c1").status_code == 204
    assert events_of(http, "delegation") == [], "the events already stored for the chat are gone"
    # The task's result arrives after the chat is gone.
    assert push(http, token, "TASK_STATE_COMPLETED", [{"text": "Deleted old.log."}]).status_code == 401
    store = Store(tmp_path / "voice_agent.sqlite")
    assert store.transcript_count("c1") == 0 and store.tasks_for_chat("c1") == []
    store.close()
    assert [e for e in http.get("/v1/replay").json()["events"] if e.get("chat_id") == "c1"] == []


async def test_a_report_that_is_still_being_written_when_its_chat_is_deleted_is_dropped(tmp_path: Path) -> None:
    store = Store(tmp_path / "voice.sqlite")
    said: list[str] = []

    class Events:
        def publish(self, kind: Any, payload: dict[str, Any], **scope: Any) -> int:
            said.append(payload.get("text", ""))
            return 1

    relay = TaskRelay(store, cast(Any, object()), cast(Any, Events()), "http://unused")
    store.add_task(DelegatedTask("t1", "c1", "p1", "work", "completed", "result", "token", None, None, True))
    writing, released = asyncio.Event(), asyncio.Event()

    async def reporter(_task: DelegatedTask) -> str:
        writing.set()
        await released.wait()
        return "It is finished."

    relay.set_reporter(reporter)
    relay.announce("t1", "Done. result")
    await writing.wait()  # the voice model is putting the result into words
    store.delete_chat("c1")
    released.set()
    await relay.close()
    assert store.transcript_count("c1") == 0, "the report is not written into a chat that is gone"
    assert said == [], "and nothing is sent out for it"
    store.close()


def test_the_note_that_a_chat_was_deleted_is_kept_for_a_week(tmp_path: Path) -> None:
    store = Store(tmp_path / "voice.sqlite")
    store.delete_chat("old")
    store._db.execute("update deleted_chats set deleted_at = '2026-01-01T00:00:00+00:00' where chat_id = 'old'")
    assert store.chat_deleted("old")
    store.delete_chat("new")  # the next delete tidies up
    assert not store.chat_deleted("old") and store.chat_deleted("new")
    store.append("new", [{"type": "ai", "data": {"content": "late"}}])
    store.save_turn("new", "m1", "late")
    assert store.transcript_count("new") == 0 and store.turn_reply("new", "m1") is None
    store.close()


def test_a_running_task_stays_selectable_however_many_newer_ones_have_ended(tmp_path: Path) -> None:
    import time as clock

    store = Store(tmp_path / "voice_agent.sqlite")
    store.add_task(DelegatedTask("old", "c1", "p1", "the long one", "working", "", "tok", None, None))
    for n in range(21):
        clock.sleep(0.002)  # tasks are ordered by when they were made
        store.add_task(DelegatedTask(f"t{n}", "c1", "p1", "quick", "completed", "", "tok", None, None))
    assert [t.task_id for t in store.tasks_for_chat("c1", open_only=True)] == ["old"]
    assert len(store.tasks_for_chat("c1")) == 20, "the plain list is still the newest twenty"
