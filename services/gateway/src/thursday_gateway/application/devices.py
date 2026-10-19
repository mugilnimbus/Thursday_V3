"""Paired devices: one-time pairing codes, device tokens, and revocation.

A pairing code is made only on this PC (localhost listener), works once, and expires after five
minutes. Claiming it returns a long random device token; only its SHA-256 hash is stored. Failed
claims are rate limited, and too many failures burn the code. Revoking a device refuses its token
at once and closes its open sockets.
"""

import asyncio
import hashlib
import hmac
import secrets
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from thursday_gateway.application.ports import DeviceRecords
from thursday_gateway.application.projects import NotFound
from thursday_gateway.domain.model import InvalidInput, clean_name

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I
CODE_LENGTH = 8
CODE_TTL = timedelta(minutes=5)
FAILURE_WINDOW_SECONDS = 60.0
MAX_FAILURES_PER_WINDOW = 5
MAX_FAILURES_PER_CODE = 10
LAST_SEEN_EVERY_SECONDS = 60.0


class RateLimited(Exception):
    pass


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalize_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


@dataclass(frozen=True, slots=True)
class PairingCode:
    code: str
    expires_at: datetime

    @property
    def display(self) -> str:
        return f"{self.code[:4]}-{self.code[4:]}"


@dataclass(slots=True)
class _Active:
    digest: str
    expires_at: datetime
    failures: int = 0


class DeviceService:
    def __init__(self, devices: DeviceRecords, clock: Callable[[], float] = time.monotonic) -> None:
        self._devices = devices
        self._clock = clock
        self._active: _Active | None = None
        self._failures: deque[float] = deque()
        self._seen: dict[str, float] = {}
        self._watchers: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Event]]] = {}

    # --- pairing -----------------------------------------------------------------------------
    def create_code(self) -> PairingCode:
        """A new code replaces any earlier one."""
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        expires = datetime.now(UTC) + CODE_TTL
        self._active = _Active(token_hash(code), expires)
        return PairingCode(code, expires)

    def claim(self, code: str, name: str) -> tuple[str, str]:
        """Burn the code and return (device_id, token). The token is shown once and never stored."""
        now = self._clock()
        while self._failures and now - self._failures[0] > FAILURE_WINDOW_SECONDS:
            self._failures.popleft()
        if len(self._failures) >= MAX_FAILURES_PER_WINDOW:
            raise RateLimited("too many pairing attempts; wait a minute and try again")
        device_name = clean_name(name, "device name")
        active = self._active
        valid = (
            active is not None
            and datetime.now(UTC) < active.expires_at
            and hmac.compare_digest(active.digest, token_hash(normalize_code(code)))
        )
        if not valid:
            self._failures.append(now)
            if active is not None:
                active.failures += 1
                if active.failures >= MAX_FAILURES_PER_CODE:
                    self._active = None
            raise InvalidInput("this pairing code is wrong or has expired; make a new one on the PC")
        self._active = None
        device_id = f"dev-{uuid.uuid4().hex[:12]}"
        token = secrets.token_urlsafe(32)
        self._devices.add(device_id, device_name, token_hash(token), datetime.now(UTC).isoformat())
        return device_id, token

    # --- tokens --------------------------------------------------------------------------------
    def authenticate(self, token: str) -> str | None:
        """The device id for a valid, unrevoked token; also records when it was last seen."""
        if len(token) < 32:
            return None
        wanted = token_hash(token)
        known = self._devices.token_hashes()
        device_id = next((r["device_id"] for r in known if hmac.compare_digest(wanted, r["token_hash"])), None)
        if device_id is not None:
            now = self._clock()
            if now - self._seen.get(device_id, -LAST_SEEN_EVERY_SECONDS) >= LAST_SEEN_EVERY_SECONDS:
                self._seen[device_id] = now
                self._devices.seen(device_id, datetime.now(UTC).isoformat())
        return device_id

    # --- management ---------------------------------------------------------------------------
    def list(self) -> list[dict[str, Any]]:
        return self._devices.list()

    def revoke(self, device_id: str) -> None:
        if not self._devices.revoke(device_id):
            raise NotFound(device_id)
        self._seen.pop(device_id, None)
        for loop, event in self._watchers.pop(device_id, []):
            loop.call_soon_threadsafe(event.set)

    def watch(self, device_id: str) -> asyncio.Event:
        """An event set when the device is revoked, so an open socket can be closed at once."""
        event = asyncio.Event()
        self._watchers.setdefault(device_id, []).append((asyncio.get_running_loop(), event))
        return event

    def unwatch(self, device_id: str, event: asyncio.Event) -> None:
        watchers = [w for w in self._watchers.get(device_id, []) if w[1] is not event]
        if watchers:
            self._watchers[device_id] = watchers
        else:
            self._watchers.pop(device_id, None)
