"""PC resource readings: CPU, RAM, network rates (psutil) and per-GPU VRAM (NVML)."""

import logging
import time

import psutil
from thursday_contracts.metrics import GpuSample

log = logging.getLogger(__name__)
MB = 1024 * 1024


class HostReader:
    def __init__(self) -> None:
        psutil.cpu_percent(None)  # first call primes the counter
        counters = psutil.net_io_counters()
        self._net = (time.monotonic(), counters.bytes_recv, counters.bytes_sent)
        self._nvml = self._init_nvml()

    @staticmethod
    def _init_nvml() -> object | None:
        try:
            import pynvml

            pynvml.nvmlInit()
            return pynvml
        except Exception as exc:  # no NVIDIA driver: GPU readings are simply absent
            log.info("GPU metrics unavailable: %s", type(exc).__name__)
            return None

    def cpu_ram(self) -> tuple[float, int, int]:
        memory = psutil.virtual_memory()
        return psutil.cpu_percent(None), (memory.total - memory.available) // MB, memory.total // MB

    def network(self) -> tuple[float, float]:
        now = time.monotonic()
        counters = psutil.net_io_counters()
        then, rx, tx = self._net
        self._net = (now, counters.bytes_recv, counters.bytes_sent)
        elapsed = max(now - then, 1e-6)
        return (counters.bytes_recv - rx) / elapsed, (counters.bytes_sent - tx) / elapsed

    def gpus(self) -> list[GpuSample]:
        nvml = self._nvml
        if nvml is None:
            return []
        samples = []
        try:
            for index in range(nvml.nvmlDeviceGetCount()):  # type: ignore[attr-defined]
                handle = nvml.nvmlDeviceGetHandleByIndex(index)  # type: ignore[attr-defined]
                memory = nvml.nvmlDeviceGetMemoryInfo(handle)  # type: ignore[attr-defined]
                try:
                    util: int | None = int(nvml.nvmlDeviceGetUtilizationRates(handle).gpu)  # type: ignore[attr-defined]
                except Exception:
                    util = None
                name = nvml.nvmlDeviceGetName(handle)  # type: ignore[attr-defined]
                samples.append(
                    GpuSample(
                        index=index,
                        name=name if isinstance(name, str) else name.decode(),
                        vram_used_mb=int(memory.used) // MB,
                        vram_total_mb=int(memory.total) // MB,
                        util_percent=util,
                    )
                )
        except Exception as exc:
            log.warning("GPU reading failed: %s", type(exc).__name__)
        return samples
