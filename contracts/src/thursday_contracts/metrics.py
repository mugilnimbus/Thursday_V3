"""Metrics sample pushed by the metrics collector to the gateway (`POST /v1/metrics`).

Services expose `GET /metrics` (JSON, localhost only): a flat map of numbers and short
strings. The collector adds PC resources and each service's scrape latency.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

METRICS_PATH = "/metrics"

MetricValue = float | int | str | bool | None


class GpuSample(BaseModel):
    index: int
    name: str
    vram_used_mb: int
    vram_total_mb: int
    util_percent: int | None = None


class ServiceSample(BaseModel):
    name: str
    up: bool
    latency_ms: float | None = None
    metrics: dict[str, MetricValue] = Field(default_factory=dict)


class MetricsSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ts: datetime
    cpu_percent: float
    ram_used_mb: int
    ram_total_mb: int
    net_rx_bytes_per_s: float
    net_tx_bytes_per_s: float
    gpus: list[GpuSample] = Field(default_factory=list)
    services: list[ServiceSample] = Field(default_factory=list)
