"""Pairing and paired devices (`/v1/devices`).

- Making a pairing code is mounted only on the localhost listener.
- Claiming a code needs no device token (the phone has none yet) and is rate limited.
- Listing and revoking devices need the listener's normal auth.
"""

from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from thursday_gateway.application.devices import DeviceService
from thursday_gateway.infrastructure.tailnet import TailnetAddress


class ClaimIn(BaseModel):
    code: str = Field(min_length=4, max_length=32)
    name: str = Field(min_length=1, max_length=120)


def pairing_uri(url: str, code: str) -> str:
    """What the QR code holds; the phone app parses it."""
    return "thursday://pair?" + urlencode({"url": url, "code": code})


def build_pairing_router(devices: DeviceService, address: TailnetAddress) -> APIRouter:
    r = APIRouter(prefix="/v1/devices")

    @r.post("/pairing", status_code=201)
    async def create_code() -> dict[str, Any]:
        code = devices.create_code()
        url = await address.url()
        return {
            "code": code.display,
            "expires_at": code.expires_at.isoformat(),
            "address": url,
            "pairing_uri": pairing_uri(url, code.code) if url else None,
        }

    return r


def build_claim_router(devices: DeviceService) -> APIRouter:
    r = APIRouter(prefix="/v1/devices")

    @r.post("/claim", status_code=201)
    async def claim(body: ClaimIn) -> dict[str, Any]:
        device_id, token = devices.claim(body.code, body.name)
        return {"device_id": device_id, "token": token}

    return r


def build_devices_router(devices: DeviceService, auth: Callable[..., Awaitable[None]]) -> APIRouter:
    r = APIRouter(prefix="/v1/devices", dependencies=[Depends(auth)])

    @r.get("")
    async def list_devices() -> dict[str, Any]:
        return {"devices": devices.list()}

    @r.delete("/{device_id}", status_code=204)
    async def revoke(device_id: str) -> None:
        devices.revoke(device_id)

    return r
