"""Asks each service to copy its own data into a backup folder."""

from typing import Any

import httpx
from pydantic import SecretStr


class ServiceBackups:
    def __init__(self, services: dict[str, str], token: SecretStr, client: httpx.AsyncClient | None = None) -> None:
        self._services = services  # name: base address
        self._headers = {"Authorization": f"Bearer {token.get_secret_value()}"}
        self._client = client or httpx.AsyncClient(timeout=120)

    def names(self) -> list[str]:
        return list(self._services)

    async def copy(self, name: str, target_dir: str) -> dict[str, Any]:
        """`{"ok": True, "files": {...}}`, or `{"ok": False, "error": ...}` when the service is down or refuses."""
        try:
            response = await self._client.post(
                f"{self._services[name]}/v1/backup", json={"target_dir": target_dir}, headers=self._headers
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            return {"ok": False, "error": type(exc).__name__}
        return {"ok": True, "files": response.json().get("files", {})}
