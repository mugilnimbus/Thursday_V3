"""This PC's address on the tailnet, for the pairing QR code.

Uses GATEWAY_PUBLIC_URL when set; otherwise asks the local Tailscale client for this machine's
DNS name (the HTTPS name `tailscale serve` answers on). The answer is cached for a while.
"""

import asyncio
import json
import logging
import os
import shutil
import time
from pathlib import Path

log = logging.getLogger(__name__)
CACHE_SECONDS = 600.0
# The Windows installer does not always put the CLI on PATH.
WINDOWS_PATHS = [Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Tailscale" / "tailscale.exe"]


class TailnetAddress:
    def __init__(self, configured: str) -> None:
        self._configured = configured.strip().rstrip("/")
        self._cached: tuple[float, str | None] | None = None

    async def url(self) -> str | None:
        if self._configured:
            return self._configured
        if self._cached and time.monotonic() - self._cached[0] < CACHE_SECONDS:
            return self._cached[1]
        found = await self._ask_tailscale()
        self._cached = (time.monotonic(), found)
        return found

    @staticmethod
    async def _ask_tailscale() -> str | None:
        exe = shutil.which("tailscale") or next((str(p) for p in WINDOWS_PATHS if p.is_file()), None)
        if exe is None:
            return None
        try:
            proc = await asyncio.create_subprocess_exec(
                exe, "status", "--json", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            name = str(json.loads(out).get("Self", {}).get("DNSName", "")).rstrip(".")
        except (OSError, TimeoutError, ValueError, AttributeError):
            log.warning("could not read the tailnet name from tailscale")
            return None
        return f"https://{name}" if name else None
