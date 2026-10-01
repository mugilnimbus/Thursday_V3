"""Harness: the real main agent app (SDK, ingress guard, store, tool-server child process) with a
scripted chat model, driven over A2A JSON-RPC exactly as the gateway and voice agent do."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from pydantic import SecretStr
from thursday_contracts.task_control import EXTENSIONS_HEADER, TASK_CONTROL_EXTENSION_URI
from thursday_llm.providers import LoadedModel, ModelInfo
from thursday_main_agent.bootstrap.main import MainAgentSettings, create_app

TOKEN = "test-service-token"
Script = Callable[[list[BaseMessage]], AIMessage]


class ScriptedChat:
    """Stands in for ChatOpenAI. Replies are a pure function of the conversation, so re-runs agree."""

    def __init__(self, script: Script) -> None:
        self.script = script
        self.calls = 0

    def bind_tools(self, tools: list[dict[str, Any]]) -> "ScriptedChat":
        self.tool_names = [t["function"]["name"] for t in tools]
        return self

    async def astream(self, messages: list[BaseMessage]) -> AsyncIterator[AIMessageChunk]:
        self.calls += 1
        reply = self.script(messages)
        chunks = [
            {"name": c["name"], "args": json.dumps(c["args"]), "id": c["id"], "index": i, "type": "tool_call_chunk"}
            for i, c in enumerate(reply.tool_calls)
        ]
        yield AIMessageChunk(
            content=reply.content,
            tool_call_chunks=chunks,  # type: ignore[arg-type]
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )


class FakeProvider:
    supports_lifecycle = False
    loaded = None

    def __init__(self, context_length: int = 32000) -> None:
        self.context_length = context_length

    async def list_models(self) -> list[ModelInfo]:
        return []

    async def ensure_loaded(self) -> LoadedModel:
        return LoadedModel("scripted", None, self.context_length, adopted=True)

    async def unload(self) -> None: ...

    async def reload(self, load: Any = None) -> LoadedModel:
        return await self.ensure_loaded()

    async def reachable(self) -> bool:
        return True

    async def aclose(self) -> None: ...


def tool_results(messages: list[BaseMessage]) -> list[ToolMessage]:
    return [m for m in messages if isinstance(m, ToolMessage)]


def call(name: str, args: dict[str, Any], n: int = 1) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": f"call-{n}"}])


@dataclass
class Harness:
    client: httpx.AsyncClient
    workspace: Path
    data_dir: Path
    chat: ScriptedChat

    async def rpc(self, method: str, params: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        response = await self.client.post(
            "/a2a",
            json={"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method, "params": params},
            headers=headers or {},
        )
        return response.json()

    async def new_task(self, text: str, chat_id: str = "chat-1") -> str:
        body = await self.rpc(
            "SendMessage",
            {
                "message": {
                    "messageId": str(uuid.uuid4()),
                    "role": "ROLE_USER",
                    "contextId": chat_id,
                    "parts": [{"text": text}],
                    "metadata": {"thursday.project_id": "proj-1", "thursday.project_folder": str(self.workspace)},
                },
                "configuration": {"returnImmediately": True},
            },
        )
        assert "result" in body, body
        return body["result"]["task"]["id"]

    async def answer(self, task_id: str, approval_id: str, decision: str, chat_id: str = "chat-1") -> dict[str, Any]:
        return await self.rpc(
            "SendMessage",
            {
                "message": {
                    "messageId": str(uuid.uuid4()),
                    "role": "ROLE_USER",
                    "taskId": task_id,
                    "contextId": chat_id,
                    "parts": [
                        {"data": {"kind": "thursday.approval_answer", "approval_id": approval_id, "decision": decision}}
                    ],
                    "metadata": {"thursday.answered_by": "test"},
                },
                "configuration": {"returnImmediately": True},
            },
        )

    async def control(self, method: str, task_id: str) -> dict[str, Any]:
        return await self.rpc(method, {"id": task_id}, headers={EXTENSIONS_HEADER: TASK_CONTROL_EXTENSION_URI})

    async def get(self, task_id: str) -> dict[str, Any]:
        return (await self.rpc("GetTask", {"id": task_id}))["result"]

    async def wait(self, task_id: str, *states: str, timeout: float = 30, paused: bool = False) -> dict[str, Any]:
        wanted = {f"TASK_STATE_{s.upper()}" for s in states}
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            task = await self.get(task_id)
            is_paused = (task.get("metadata") or {}).get("pause_state") == "paused"
            if task["status"]["state"] in wanted and (not paused or is_paused):
                return task
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError(f"task stayed {task['status']['state']} (wanted {wanted}): {task['status']}")
            await asyncio.sleep(0.1)

    @staticmethod
    def approval_of(task: dict[str, Any]) -> dict[str, Any]:
        return next(p["data"] for p in task["status"]["message"]["parts"] if "data" in p)

    async def events(self, type_: str | None = None) -> list[dict[str, Any]]:
        body = (await self.client.get("/v1/replay", params={"limit": 2000})).json()["events"]
        return [e for e in body if type_ is None or e["type"] == type_]


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "old.log").write_text("old", encoding="utf-8")
    return ws


@pytest.fixture
def start(tmp_path: Path, workspace: Path, monkeypatch: pytest.MonkeyPatch):
    """Factory: start the app with a script; the same data folder is reused, so restarts are real."""
    env = tmp_path / "test.env"
    env.write_text("", encoding="utf-8")
    monkeypatch.setenv("THURSDAY_ENV_FILE", str(env))
    monkeypatch.setenv("THURSDAY_DATA_DIR", str(tmp_path / "data"))
    data_dir = tmp_path / "data" / "main_agent"
    data_dir.mkdir(parents=True, exist_ok=True)

    def factory(script: Script, approval_seconds: float = 30, context_length: int = 32000):
        settings = MainAgentSettings(
            _env_file=None,  # pyright: ignore[reportCallIssue]
            thursday_service_token=SecretStr(TOKEN),
            gateway_localhost_port=9,
            thursday_data_dir=str(tmp_path / "data"),
        )
        chat = ScriptedChat(script)
        app = create_app(
            settings,
            data_dir,
            chat_model=chat,
            provider=FakeProvider(context_length),  # pyright: ignore[reportArgumentType]
            approval_timeout=timedelta(seconds=approval_seconds),
        )

        class Running:
            async def __aenter__(self) -> Harness:
                self._lifespan = app.router.lifespan_context(app)
                await self._lifespan.__aenter__()
                client = httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://main",
                    headers={"Authorization": f"Bearer {TOKEN}", "A2A-Version": "1.0"},
                    timeout=30,
                )
                self._client = client
                return Harness(client, workspace, data_dir, chat)

            async def __aexit__(self, *exc: object) -> None:
                await self._client.aclose()
                await self._lifespan.__aexit__(None, None, None)

        return Running()

    return factory
