import json

import anyio
import httpx
from thursday_contracts.metrics import GpuSample, MetricsSample
from thursday_metrics_collector.application.collector import Collector, Target


class FakeHost:
    def cpu_ram(self) -> tuple[float, int, int]:
        return 12.5, 30_000, 64_000

    def network(self) -> tuple[float, float]:
        return 1000.0, 50.0

    def gpus(self) -> list[GpuSample]:
        return [GpuSample(index=0, name="GPU", vram_used_mb=10_000, vram_total_mb=12_288, util_percent=40)]


def test_sample_scrapes_services_marks_down_ones_and_pushes() -> None:
    pushed: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "main":
            return httpx.Response(200, json={"open_tasks": 2, "nested": {"dropped": True}})
        if request.url.host == "voice":
            raise httpx.ConnectError("down")
        pushed.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer tok"
        return httpx.Response(204)

    collector = Collector(
        FakeHost(),
        [Target("main_agent", "http://main"), Target("voice_agent", "http://voice")],
        "http://gateway",
        "tok",
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    async def once() -> MetricsSample:
        sample = await collector.sample()
        assert await collector.push(sample)
        return sample

    sample = anyio.run(once)
    by_name = {s.name: s for s in sample.services}
    assert by_name["main_agent"].up and by_name["main_agent"].metrics == {"open_tasks": 2}
    assert by_name["main_agent"].latency_ms is not None
    assert not by_name["voice_agent"].up
    assert MetricsSample.model_validate(pushed[0]).gpus[0].vram_used_mb == 10_000


def test_real_host_readings_are_sane() -> None:
    from thursday_metrics_collector.infrastructure.host import HostReader

    host = HostReader()
    cpu, used, total = host.cpu_ram()
    assert 0 <= cpu <= 100 and 0 < used <= total
    for gpu in host.gpus():
        assert 0 < gpu.vram_used_mb <= gpu.vram_total_mb


def test_stored_data_is_measured_per_service_and_only_now_and_then(tmp_path) -> None:
    from thursday_metrics_collector.infrastructure.disk import DataFolders

    for name, files in (
        ("main_agent", {"main_agent.sqlite": 3000, "checkpoints.sqlite": 9000, "checkpoints.sqlite-wal": 500}),
        ("gateway", {"gateway.sqlite": 2000}),
        ("speech", {"kokoro-v1.0.onnx": 50_000}),  # a program file, not data that grows
    ):
        (tmp_path / "services" / name).mkdir(parents=True)
        for file, size in files.items():
            (tmp_path / "services" / name / file).write_bytes(b"x" * size)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "gateway.log").write_bytes(b"x" * 700)
    folders = DataFolders(tmp_path)
    assert [(s.name, s.bytes) for s in folders.sizes()] == [("main_agent", 12_500), ("gateway", 2000), ("logs", 700)]
    assert DataFolders(tmp_path / "missing").sizes() == []

    class Counting:
        calls = 0

        def sizes(self):
            self.calls += 1
            return folders.sizes()

    storage = Counting()
    collector = Collector(
        FakeHost(),
        [],
        "http://gateway",
        "tok",
        httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(204))),
        storage,
    )

    async def twice() -> MetricsSample:
        await collector.sample()
        return await collector.sample()

    sample = anyio.run(twice)
    assert sum(s.bytes for s in sample.storage) == 15_200 and storage.calls == 1, (
        "every sample carries it, measured once a minute"
    )
