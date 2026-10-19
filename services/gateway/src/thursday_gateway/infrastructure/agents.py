"""Clients for the two agents, with timeouts and stable errors.

Main agent: A2A JSON-RPC (task control, approval answers) and its management API.
Voice agent: the internal chat API, one streamed turn per user message (NDJSON lines).
"""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
from pydantic import SecretStr
from thursday_contracts.approvals import APPROVAL_ANSWER_KIND
from thursday_contracts.retention import RETENTION_PATH
from thursday_contracts.task_control import EXTENSIONS_HEADER, TASK_CONTROL_EXTENSION_URI

from thursday_gateway.application.errors import AgentRefused, AgentUnavailable

log = logging.getLogger(__name__)
_DROPPED = (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError)


async def _ready(client: httpx.AsyncClient, base: str, who: str) -> dict[str, Any] | None:
    """The agent's readiness report, or None when it does not give one in time.

    A connection kept open since the last check can have been closed by the agent in the meantime: it restarted,
    or it closed the connection in the very moment it is used again (the services keep an unused connection
    longer than their callers do, so that this does not happen between two checks; see `thursday_runtime.serve`).
    A closed connection says nothing about the agent, so the question is asked once more, on a new one. Every
    miss is logged with its kind, so a false alarm can be told from an agent that really stopped.
    """
    for attempt in (1, 2):
        try:
            return (await client.get(f"{base}/ready", timeout=3)).json()
        except _DROPPED as exc:
            if attempt == 2:
                log.info("the %s dropped two readiness checks (%s)", who, type(exc).__name__)
        except (httpx.HTTPError, ValueError) as exc:
            log.info("the %s did not answer a readiness check (%s)", who, type(exc).__name__)
            return None
    return None


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

    async def set_retention(self, days: int) -> None:
        response = await self.management("PUT", RETENTION_PATH, json={"days": days})
        if response.status_code >= 400:
            raise AgentRefused(response.status_code, f"main agent answered {response.status_code}")

    async def ready(self) -> dict[str, Any] | None:
        return await _ready(self._client, self._base, "main agent")


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

    async def direct(self, chat_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Start a task from the user's words, unchanged, without the voice model. Raises AgentUnavailable when the
        voice agent or the main agent cannot be reached (the message stays queued) and AgentRefused when the task
        was refused (the message fails with the reason)."""
        try:
            response = await self._client.post(
                f"{self._base}/v1/chats/{chat_id}/direct", json=body, headers=self._headers
            )
        except httpx.HTTPError as exc:
            raise AgentUnavailable(f"voice agent unreachable ({type(exc).__name__})") from exc
        if response.status_code >= 500:
            raise AgentUnavailable(f"voice agent answered {response.status_code}")
        if response.status_code >= 400:
            try:
                detail = str(response.json().get("detail", ""))
            except ValueError:
                detail = response.text
            raise AgentRefused(response.status_code, detail[:300] or f"HTTP {response.status_code}")
        return response.json()

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Management calls (LLM settings, prompts, model lifecycle)."""
        try:
            return await self._client.request(
                method, f"{self._base}/v1{path}", headers=self._headers, timeout=900, **kwargs
            )
        except httpx.HTTPError as exc:
            raise AgentUnavailable(f"voice agent unreachable ({type(exc).__name__})") from exc

    async def hear(self, wav: bytes) -> dict[str, Any] | None:
        """What the voice model itself hears in a WAV clip, or None when it cannot (then speech-to-text is used)."""
        try:
            response = await self._client.post(f"{self._base}/v1/hear", headers=self._headers, content=wav, timeout=120)
        except httpx.HTTPError:
            return None
        return response.json() if response.status_code == 200 else None

    async def set_retention(self, days: int) -> None:
        response = await self.request("PUT", RETENTION_PATH, json={"days": days})
        if response.status_code >= 400:
            raise AgentRefused(response.status_code, f"voice agent answered {response.status_code}")

    async def delete_chat(self, chat_id: str) -> None:
        try:
            response = await self._client.delete(f"{self._base}/v1/chats/{chat_id}", headers=self._headers)
        except httpx.HTTPError as exc:
            raise AgentUnavailable("voice agent unreachable") from exc
        if response.status_code >= 400:
            raise AgentRefused(response.status_code, "voice agent refused the delete")

    async def ready(self) -> dict[str, Any] | None:
        return await _ready(self._client, self._base, "voice agent")
