"""Clients for the two agents, with timeouts and stable errors.

Main agent: A2A JSON-RPC (task control, approval answers) and its management API.
Voice agent: the internal chat API, one streamed turn per user message (NDJSON lines).
"""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
from pydantic import SecretStr
from thursday_contracts.approvals import APPROVAL_ANSWER_KIND
from thursday_contracts.task_control import EXTENSIONS_HEADER, TASK_CONTROL_EXTENSION_URI


class AgentUnavailable(Exception):
    """The agent could not be reached."""


class AgentRefused(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


class MainAgentClient:
    def __init__(self, base_url: str, token: SecretStr, client: httpx.AsyncClient | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=10)
        self._headers = {"Authorization": f"Bearer {token.get_secret_value()}", "A2A-Version": "1.0"}

    async def _rpc(self, method: str, params: dict[str, Any], *, extension: bool = False) -> dict[str, Any]:
        headers = {**self._headers, **({EXTENSIONS_HEADER: TASK_CONTROL_EXTENSION_URI} if extension else {})}
        try:
            response = await self._client.post(
                f"{self._base}/a2a",
                headers=headers,
                json={"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method, "params": params},
            )
        except httpx.HTTPError as exc:
            raise AgentUnavailable(f"main agent unreachable ({type(exc).__name__})") from exc
        if response.status_code >= 400:
            raise AgentRefused(response.status_code, f"main agent answered {response.status_code}")
        body = response.json()
        if "error" in body:
            raise AgentRefused(int(body["error"].get("code", 0)), str(body["error"].get("message", "")))
        return body.get("result") or {}

    async def answer_approval(self, task_id: str, chat_id: str, approval_id: str, decision: str) -> None:
        message = {
            "messageId": str(uuid.uuid4()),
            "role": "ROLE_USER",
            "taskId": task_id,
            "contextId": chat_id,
            "parts": [{"data": {"kind": APPROVAL_ANSWER_KIND, "approval_id": approval_id, "decision": decision}}],
            "metadata": {"thursday.answered_by": "gateway"},
        }
        await self._rpc("SendMessage", {"message": message, "configuration": {"returnImmediately": True}})

    async def cancel(self, task_id: str) -> dict[str, Any]:
        return await self._rpc("CancelTask", {"id": task_id})

    async def pause(self, task_id: str) -> dict[str, Any]:
        return await self._rpc("PauseTask", {"id": task_id}, extension=True)

    async def resume(self, task_id: str) -> dict[str, Any]:
        return await self._rpc("ResumeTask", {"id": task_id}, extension=True)

    async def management(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return await self._client.request(
                method, f"{self._base}/v1{path}", headers=self._headers, timeout=900, **kwargs
            )
        except httpx.HTTPError as exc:
            raise AgentUnavailable(f"main agent unreachable ({type(exc).__name__})") from exc

    async def ready(self) -> dict[str, Any] | None:
        try:
            response = await self._client.get(f"{self._base}/ready", timeout=3)
        except httpx.HTTPError:
            return None
        return response.json()


class VoiceAgentClient:
    def __init__(self, base_url: str, token: SecretStr, client: httpx.AsyncClient | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(10, read=300))
        self._headers = {"Authorization": f"Bearer {token.get_secret_value()}"}

    async def turn(self, chat_id: str, body: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        """Stream one user turn. Raises AgentUnavailable if the voice agent cannot be reached."""
        try:
            async with self._client.stream(
                "POST", f"{self._base}/v1/chats/{chat_id}/turns", json=body, headers=self._headers
            ) as response:
                if response.status_code >= 500:
                    raise AgentUnavailable(f"voice agent answered {response.status_code}")
                if response.status_code >= 400:
                    raise AgentRefused(response.status_code, (await response.aread()).decode()[:300])
                async for line in response.aiter_lines():
                    if line.strip():
                        yield json.loads(line)
        except httpx.HTTPError as exc:
            raise AgentUnavailable(f"voice agent unreachable ({type(exc).__name__})") from exc

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Management calls (LLM settings, prompts, model lifecycle)."""
        try:
            return await self._client.request(
                method, f"{self._base}/v1{path}", headers=self._headers, timeout=900, **kwargs
            )
        except httpx.HTTPError as exc:
            raise AgentUnavailable(f"voice agent unreachable ({type(exc).__name__})") from exc

    async def delete_chat(self, chat_id: str) -> None:
        try:
            response = await self._client.delete(f"{self._base}/v1/chats/{chat_id}", headers=self._headers)
        except httpx.HTTPError as exc:
            raise AgentUnavailable("voice agent unreachable") from exc
        if response.status_code >= 400:
            raise AgentRefused(response.status_code, "voice agent refused the delete")

    async def ready(self) -> dict[str, Any] | None:
        try:
            response = await self._client.get(f"{self._base}/ready", timeout=3)
        except httpx.HTTPError:
            return None
        return response.json()
