import json
import os

import httpx
import pytest
from pydantic import SecretStr
from thursday_llm.capture import CapturedExchange, CaptureTransport
from thursday_llm.config import LlmConfig, LoadParameters, ProviderKind
from thursday_llm.providers import LmStudioProvider, ProviderError


def config(**kw: object) -> LlmConfig:
    base = {
        "provider": ProviderKind.LMSTUDIO,
        "base_url": "http://127.0.0.1:1234",
        "model": "m/one",
        "api_key": SecretStr("k"),
        "load": LoadParameters(context_length=8192, flash_attention=True),
    }
    base.update(kw)
    return LlmConfig(**base)  # type: ignore[arg-type]


class FakeLmStudio:
    def __init__(self, loaded: bool) -> None:
        self.instances: list[dict] = [{"id": "m/one", "config": {"context_length": 4096}}] if loaded else []
        self.load_bodies: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer k"
        if request.url.path == "/api/v1/models":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "type": "llm",
                            "key": "m/one",
                            "loaded_instances": self.instances,
                            "max_context_length": 131072,
                            "capabilities": {"trained_for_tool_use": True},
                        },
                        {"type": "embedding", "key": "e/one", "loaded_instances": []},
                    ]
                },
            )
        if request.url.path == "/api/v1/models/load":
            body = json.loads(request.content)
            self.load_bodies.append(body)
            self.instances.append({"id": "m/one", "config": {"context_length": body.get("context_length")}})
            return httpx.Response(
                200,
                json={
                    "instance_id": "m/one",
                    "load_time_seconds": 8.5,
                    "load_config": {"context_length": body.get("context_length")},
                },
            )
        if request.url.path == "/api/v1/models/unload":
            self.instances = [i for i in self.instances if i["id"] != json.loads(request.content)["instance_id"]]
            return httpx.Response(200, json={})
        return httpx.Response(404)


def provider(fake: FakeLmStudio, cfg: LlmConfig | None = None) -> LmStudioProvider:
    client = httpx.AsyncClient(
        base_url="http://lm", headers={"Authorization": "Bearer k"}, transport=httpx.MockTransport(fake.handler)
    )
    return LmStudioProvider(cfg or config(), client)


async def test_adopts_a_loaded_model_without_loading_again() -> None:
    fake = FakeLmStudio(loaded=True)
    loaded = await provider(fake).ensure_loaded()
    assert loaded.adopted and loaded.context_length == 4096 and fake.load_bodies == []


async def test_loads_with_configured_parameters_when_not_loaded() -> None:
    fake = FakeLmStudio(loaded=False)
    loaded = await provider(fake).ensure_loaded()
    assert not loaded.adopted and loaded.context_length == 8192 and loaded.load_seconds == 8.5
    assert fake.load_bodies == [
        {"model": "m/one", "echo_load_config": True, "context_length": 8192, "flash_attention": True}
    ]


async def test_concurrent_callers_trigger_a_single_load() -> None:
    import asyncio

    fake = FakeLmStudio(loaded=False)
    p = provider(fake)
    await asyncio.gather(*(p.ensure_loaded() for _ in range(5)))
    assert len(fake.load_bodies) == 1


async def test_reload_applies_new_parameters() -> None:
    fake = FakeLmStudio(loaded=True)
    loaded = await provider(fake).reload(LoadParameters(context_length=16384))
    assert loaded.context_length == 16384 and len(fake.instances) == 1


async def test_list_models_skips_embeddings() -> None:
    models = await provider(FakeLmStudio(loaded=False)).list_models()
    assert [m.key for m in models] == ["m/one"] and models[0].trained_for_tool_use


async def test_load_refusal_is_a_provider_error() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/models":
            return httpx.Response(200, json={"models": []})
        return httpx.Response(400, text="not enough memory")

    client = httpx.AsyncClient(base_url="http://lm", transport=httpx.MockTransport(refuse))
    with pytest.raises(ProviderError, match="not enough memory"):
        await LmStudioProvider(config(), client).ensure_loaded()


async def test_capture_records_bodies_but_never_headers() -> None:
    seen: list[CapturedExchange] = []

    def echo(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=httpx.ByteStream(b'data: {"x": 1}\n\ndata: [DONE]\n\n'))

    client = httpx.AsyncClient(transport=CaptureTransport(seen.append, httpx.MockTransport(echo)))
    async with client.stream(
        "POST", "http://lm/v1/responses", json={"input": "hi"}, headers={"Authorization": "Bearer secret-key"}
    ) as response:
        body = b"".join([chunk async for chunk in response.aiter_bytes()])
    assert body.startswith(b"data:")
    (exchange,) = seen
    assert exchange.request_body == {"input": "hi"} and '"x": 1' in exchange.response_text
    assert "secret-key" not in repr(exchange)


@pytest.mark.parametrize(
    ("url", "off_pc"),
    [
        ("http://127.0.0.1:5000", False),
        ("http://localhost:1234", False),
        ("https://api.example.com", True),
        ("http://[::1]:8080", False),
    ],
)
def test_cloud_endpoints_are_flagged(url: str, off_pc: bool) -> None:
    assert config(base_url=url).sends_data_off_pc is off_pc


@pytest.mark.skipif(os.environ.get("THURSDAY_LIVE_LLM") != "1", reason="set THURSDAY_LIVE_LLM=1 with LM Studio running")
async def test_live_lmstudio_adopts_the_configured_main_model() -> None:
    from thursday_runtime.settings import env_file

    env = dict(
        line.split("=", 1) for line in env_file().read_text().splitlines() if "=" in line and not line.startswith("#")
    )
    cfg = LlmConfig(
        ProviderKind.LMSTUDIO,
        env["MAIN_LLM_BASE_URL"],
        env["MAIN_LLM_MODEL"],
        SecretStr(env.get("MAIN_LLM_API_KEY") or env.get("LMSTUDIO_API_TOKEN", "")),
    )
    p = LmStudioProvider(cfg)
    try:
        loaded = await p.ensure_loaded()
    finally:
        await p.aclose()
    assert loaded.context_length and loaded.context_length > 0


async def test_runtime_merges_env_with_saved_overrides_and_rebuilds() -> None:
    from thursday_llm.runtime import LlmOverrides, LlmRuntime, LoadOverrides, config_from_env

    saved: dict = {}
    env = {"key": ""}

    def base():
        return config_from_env(
            ProviderKind.LMSTUDIO,
            "http://127.0.0.1:1234",
            "m/one",
            env["key"],
            "MAIN_LLM_API_KEY",
            "shared",
            4096,
            60.0,
        )

    rt = LlmRuntime(base, lambda: saved or None, saved.update)
    assert rt.key_source == "LMSTUDIO_API_TOKEN" and rt.config.load.context_length == 4096
    first_provider = rt.provider
    await rt.update(LlmOverrides(model="m/two", load=LoadOverrides(context_length=16384)))
    assert rt.config.model == "m/two" and rt.config.load.context_length == 16384 and rt.provider is not first_provider
    assert saved["model"] == "m/two" and saved["load"]["context_length"] == 16384
    await rt.update(LlmOverrides(model=None))
    assert rt.config.model == "m/one", "null clears an override"
    env["key"] = "own"
    await rt.reload_keys()
    assert rt.key_source == "MAIN_LLM_API_KEY"
    described = rt.describe()
    assert described["api_key_set"] and "own" not in repr(described), "keys never leave the agent"
    await rt.provider.aclose()
