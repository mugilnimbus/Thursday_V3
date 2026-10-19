"""Client for the local speech service."""

from typing import Any

import httpx
from pydantic import SecretStr

from thursday_gateway.application.errors import AgentRefused, AgentUnavailable


class SpeechClient:
    def __init__(self, base_url: str, token: SecretStr, client: httpx.AsyncClient | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(10, read=300))
        self._headers = {"Authorization": f"Bearer {token.get_secret_value()}"}

    async def call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(method, f"{self._base}/v1{path}", headers=self._headers, **kwargs)
        except httpx.HTTPError as exc:
            raise AgentUnavailable(f"the speech service is not running ({type(exc).__name__})") from exc
        if response.status_code >= 400:
            detail = response.json().get("detail", "") if "json" in response.headers.get("content-type", "") else ""
            raise AgentRefused(response.status_code, str(detail) or "the speech service refused the request")
        return response
