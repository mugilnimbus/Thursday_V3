"""A2A client to the main agent (plain JSON-RPC over httpx, protocol 1.0)."""

import uuid
from typing import Any

import httpx
from pydantic import SecretStr
from thursday_contracts.approvals import APPROVAL_ANSWER_KIND
from thursday_contracts.task_control import EXTENSIONS_HEADER, TASK_CONTROL_EXTENSION_URI


class MainAgentUnavailable(Exception):
    pass


class MainAgentRefused(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


class MainAgentClient:
    def __init__(self, base_url: str, token: SecretStr, client: httpx.AsyncClient | None = None) -> None:
        self._url = base_url.rstrip("/") + "/a2a"
        self._client = client or httpx.AsyncClient(timeout=15)
        self._headers = {"Authorization": f"Bearer {token.get_secret_value()}", "A2A-Version": "1.0"}

    async def _rpc(self, method: str, params: dict[str, Any], extension: bool = False) -> dict[str, Any]:
        headers = {**self._headers, **({EXTENSIONS_HEADER: TASK_CONTROL_EXTENSION_URI} if extension else {})}
        try:
            response = await self._client.post(
                self._url,
                headers=headers,
                json={"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method, "params": params},
            )
        except httpx.HTTPError as exc:
            raise MainAgentUnavailable(type(exc).__name__) from exc
        if response.status_code >= 400:
            raise MainAgentRefused(response.status_code, f"HTTP {response.status_code}")
        body = response.json()
        if "error" in body:
            raise MainAgentRefused(int(body["error"].get("code", 0)), str(body["error"].get("message", "")))
        return body.get("result") or {}

    async def start_task(
        self, chat_id: str, instruction: str, project_id: str, folder: str, push_url: str, push_token: str
    ) -> dict[str, Any]:
        message = {
            "messageId": str(uuid.uuid4()),
            "role": "ROLE_USER",
            "contextId": chat_id,
            "parts": [{"text": instruction}],
            "metadata": {"thursday.project_id": project_id, "thursday.project_folder": folder},
        }
        result = await self._rpc(
            "SendMessage",
            {
                "message": message,
                "configuration": {
                    "returnImmediately": True,
                    "taskPushNotificationConfig": {"url": push_url, "token": push_token},
                },
            },
        )
        return result["task"]

    async def get_task(self, task_id: str) -> dict[str, Any]:
        return await self._rpc("GetTask", {"id": task_id, "historyLength": 0})

    async def cancel(self, task_id: str) -> dict[str, Any]:
        return await self._rpc("CancelTask", {"id": task_id})

    async def pause(self, task_id: str) -> dict[str, Any]:
        return await self._rpc("PauseTask", {"id": task_id}, extension=True)

    async def resume(self, task_id: str) -> dict[str, Any]:
        return await self._rpc("ResumeTask", {"id": task_id}, extension=True)

    async def answer(self, task_id: str, chat_id: str, approval_id: str, decision: str) -> None:
        message = {
            "messageId": str(uuid.uuid4()),
            "role": "ROLE_USER",
            "taskId": task_id,
            "contextId": chat_id,
            "parts": [{"data": {"kind": APPROVAL_ANSWER_KIND, "approval_id": approval_id, "decision": decision}}],
            "metadata": {"thursday.answered_by": "voice"},
        }
        await self._rpc("SendMessage", {"message": message, "configuration": {"returnImmediately": True}})
