"""Sampling loop: PC resources plus a scrape of each service's `/metrics`, pushed to the gateway.

In-memory only. A missed scrape or push is a gap, never a retry backlog.
"""

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import httpx
from thursday_contracts.metrics import METRICS_PATH, GpuSample, MetricsSample, ServiceSample

log = logging.getLogger(__name__)


class Host(Protocol):
    def cpu_ram(self) -> tuple[float, int, int]: ...

    def network(self) -> tuple[float, float]: ...

    def gpus(self) -> list[GpuSample]: ...


@dataclass(frozen=True, slots=True)
class Target:
    name: str
    base_url: str


class Collector:
    def __init__(
        self, host: Host, targets: list[Target], gateway_url: str, token: str, client: httpx.AsyncClient | None = None
    ) -> None:
        self._host = host
        self._targets = targets
        self._push_url = gateway_url.rstrip("/") + "/v1/metrics"
        self._headers = {"Authorization": f"Bearer {token}"}
        self._client = client or httpx.AsyncClient(timeout=3)
        self.last: MetricsSample | None = None
        self.pushes_failed = 0

    async def _scrape(self, target: Target) -> ServiceSample:
        started = time.perf_counter()
        try:
            response = await self._client.get(target.base_url.rstrip("/") + METRICS_PATH)
            response.raise_for_status()
            metrics = {k: v for k, v in response.json().items() if isinstance(v, int | float | str | bool) or v is None}
        except (httpx.HTTPError, ValueError, AttributeError):
            return ServiceSample(name=target.name, up=False)
        return ServiceSample(
            name=target.name, up=True, latency_ms=round((time.perf_counter() - started) * 1000, 1), metrics=metrics
        )

    async def sample(self) -> MetricsSample:
        cpu, ram_used, ram_total = self._host.cpu_ram()
        rx, tx = self._host.network()
        services = await asyncio.gather(*(self._scrape(t) for t in self._targets))
        return MetricsSample(
            ts=datetime.now(UTC),
            cpu_percent=cpu,
            ram_used_mb=ram_used,
            ram_total_mb=ram_total,
            net_rx_bytes_per_s=round(rx, 1),
            net_tx_bytes_per_s=round(tx, 1),
            gpus=await asyncio.to_thread(self._host.gpus),
            services=list(services),
        )

    async def push(self, sample: MetricsSample) -> bool:
        try:
            response = await self._client.post(
                self._push_url,
                content=sample.model_dump_json(),
                headers={**self._headers, "Content-Type": "application/json"},
            )
            response.raise_for_status()
        except httpx.HTTPError:
            self.pushes_failed += 1
            return False
        return True

    async def run(self, stop: asyncio.Event, interval: float) -> None:
        while not stop.is_set():
            started = time.monotonic()
            try:
                self.last = await self.sample()
                await self.push(self.last)
            except Exception:
                log.exception("metrics sample failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=max(0.5, interval - (time.monotonic() - started)))
