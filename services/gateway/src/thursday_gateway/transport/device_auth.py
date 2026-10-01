"""Device-token authentication for the proxy listener (tailnet traffic).

Tokens are stored as SHA-256 hashes; a revoked device is refused. The proxy listener
never trusts the network address, because `tailscale serve` makes every request look
like localhost.
"""

import asyncio
import contextlib
from collections.abc import Awaitable

from fastapi import HTTPException, Request, WebSocket, status

from thursday_gateway.application.devices import DeviceService, token_hash

__all__ = ["DeviceAuth", "token_hash", "trusted_local"]


def bearer(header: str) -> str:
    scheme, _, token = header.partition(" ")
    return token if scheme.lower() == "bearer" else ""


class DeviceAuth:
    def __init__(self, devices: DeviceService) -> None:
        self._devices = devices

    def device_id(self, header: str) -> str | None:
        return self._devices.authenticate(bearer(header))

    async def __call__(self, request: Request) -> None:
        device_id = self.device_id(request.headers.get("authorization", ""))
        if device_id is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unauthenticated", headers={"WWW-Authenticate": "Bearer"})
        request.state.device_id = device_id

    async def guard(self, websocket: WebSocket, run: Awaitable[None]) -> None:
        """Run a socket handler for an authenticated device; close it the moment the device is revoked."""
        device_id = self.device_id(websocket.headers.get("authorization", ""))
        if device_id is None:
            await websocket.close(code=1008)
            if asyncio.iscoroutine(run):
                run.close()
            return
        signal = self._devices.watch(device_id)
        handler = asyncio.ensure_future(run)
        revoked = asyncio.ensure_future(signal.wait())
        try:
            done, _ = await asyncio.wait({handler, revoked}, return_when=asyncio.FIRST_COMPLETED)
            if revoked in done:
                handler.cancel()
                await asyncio.gather(handler, return_exceptions=True)
                with contextlib.suppress(RuntimeError):  # already closed
                    await websocket.close(code=1008)
        finally:
            revoked.cancel()
            if not handler.done():  # the connection itself was cancelled
                handler.cancel()
            self._devices.unwatch(device_id, signal)


async def trusted_local(request: Request) -> None:
    """The localhost listener is trusted: only software on this PC can reach it."""
