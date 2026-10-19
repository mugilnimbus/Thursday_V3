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
        SecretStr(os.environ.get("THURSDAY_LIVE_LLM_KEY", "")),
    )
    p = LmStudioProvider(cfg)
    try:
        loaded = await p.ensure_loaded()
    finally:
        await p.aclose()
    assert loaded.context_length and loaded.context_length > 0


class Keys:
    """A stand-in for the operating system's credential store."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, name: str) -> str:
        return self.values.get(name, "")

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


async def test_runtime_merges_env_with_saved_overrides_and_rebuilds() -> None:
    from thursday_llm.overrides import LlmOverrides, LoadOverrides
    from thursday_llm.runtime import LlmRuntime, config_from_env

    saved: dict = {}

    def base():
        return config_from_env(ProviderKind.LMSTUDIO, "http://127.0.0.1:1234", "m/one", 4096, 60.0)

    rt = LlmRuntime(base, lambda: saved or None, saved.update)
    assert rt.config.load.context_length == 4096 and not rt.describe()["api_key_set"]
    first_provider = rt.provider
    await rt.update(LlmOverrides(model="m/two", load=LoadOverrides(context_length=16384)))
    assert rt.config.model == "m/two" and rt.config.load.context_length == 16384 and rt.provider is not first_provider
    assert saved["model"] == "m/two" and saved["load"]["context_length"] == 16384
    await rt.update(LlmOverrides(model=None))
    assert rt.config.model == "m/one", "null clears an override"
    await rt.provider.aclose()


async def test_a_key_is_stored_per_provider_and_never_described() -> None:
    from thursday_llm.overrides import LlmOverrides
    from thursday_llm.runtime import LlmRuntime, config_from_env

    saved: dict = {}
    keys = Keys()
    rt = LlmRuntime(
        lambda: config_from_env(ProviderKind.LMSTUDIO, "http://127.0.0.1:1234", "m", None, 60.0),
        lambda: saved or None,
        saved.update,
        keys=keys,
        agent="main",
    )
    await rt.set_key("studio-secret")
    assert keys.values == {"main-llm-lmstudio": "studio-secret"}
    assert rt.config.api_key.get_secret_value() == "studio-secret"
    described = rt.describe()
    assert described["api_key_set"] and "studio-secret" not in repr(described), "keys never leave the agent"
    assert "studio-secret" not in repr(saved), "and are never saved with the other settings"

    await rt.update(LlmOverrides(provider=ProviderKind.OPENAI_COMPATIBLE, base_url="https://api.example.com"))
    assert not rt.describe()["api_key_set"], "the LM Studio key is not sent to a cloud endpoint"
    await rt.set_key("cloud-secret")
    assert rt.config.api_key.get_secret_value() == "cloud-secret"
    await rt.update(LlmOverrides(provider=ProviderKind.LMSTUDIO))
    assert rt.config.api_key.get_secret_value() == "studio-secret", "each provider keeps its own key"
    await rt.set_key("")
    assert "main-llm-lmstudio" not in keys.values and not rt.describe()["api_key_set"]
    await rt.provider.aclose()


def _sse(*events: dict) -> str:
    import json

    return "".join(f"event: {e.get('type', 'message')}\ndata: {json.dumps(e)}\n\n" for e in events)


def test_a_streamed_response_is_stored_as_the_response_it_carried() -> None:
    from thursday_llm.stream_reader import read_response

    final = {
        "id": "resp_1",
        "status": "completed",
        "model": "m",
        "tools": [{"name": "fs_read", "description": "x" * 5000}],
        "instructions": None,
        "output": [
            {"type": "reasoning", "content": [{"type": "reasoning_text", "text": "think"}]},
            {"type": "function_call", "name": "fs_read", "arguments": '{"path": "a.py"}', "call_id": "c1"},
        ],
        "usage": {"input_tokens": 10, "output_tokens": 2},
    }
    stream = _sse(
        {"type": "response.created", "response": {**final, "status": "in_progress", "output": []}},
        {"type": "response.reasoning_text.delta", "output_index": 0, "delta": "think"},
        {"type": "response.completed", "response": final},
    )
    read = read_response(stream)
    assert read["output"] == final["output"] and read["usage"] == final["usage"] and read["status"] == "completed"
    assert "tools" not in read and "instructions" not in read, "what the request already holds is not repeated"


def test_a_stream_that_ended_early_keeps_what_arrived_and_says_it_is_incomplete() -> None:
    from thursday_llm.stream_reader import read_response

    stream = (
        _sse(
            {"type": "response.created", "response": {"model": "m", "output": []}},
            {"type": "response.output_item.added", "output_index": 0, "item": {"type": "reasoning", "content": []}},
            {"type": "response.reasoning_text.delta", "output_index": 0, "delta": "I should "},
            {"type": "response.reasoning_text.delta", "output_index": 0, "delta": "read it."},
            {
                "type": "response.output_item.added",
                "output_index": 1,
                "item": {"type": "function_call", "name": "fs_read"},
            },
            {"type": "response.function_call_arguments.delta", "output_index": 1, "delta": '{"path":'},
        )
        + 'data: {"type":"response.function_call_argu'
    )
    read = read_response(stream)
    assert read["status"] == "incomplete" and read["model"] == "m"
    assert read["output"][0]["content"] == [{"type": "reasoning_text", "text": "I should read it."}]
    assert read["output"][1] == {"type": "function_call", "name": "fs_read", "arguments": '{"path":'}


def test_chat_completion_chunks_become_one_message() -> None:
    from thursday_llm.stream_reader import read_response

    def chunk(delta: dict, finish: str | None = None, **more: object) -> dict:
        return {"model": "gemma", "choices": [{"delta": delta, "finish_reason": finish}], **more}

    stream = (
        _sse(
            chunk({"role": "assistant", "reasoning_content": "hm "}),
            chunk({"reasoning_content": "ok"}),
            chunk({"content": "Hel"}),
            chunk({"content": "lo"}),
            chunk({"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "fs_read", "arguments": '{"pa'}}]}),
            chunk({"tool_calls": [{"index": 0, "function": {"arguments": 'th":"a"}'}}]}, "tool_calls"),
            {"model": "gemma", "choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 3}},
        )
        + "data: [DONE]\n\n"
    )
    read = read_response(stream)
    message = read["choices"][0]["message"]
    assert message["content"] == "Hello" and message["reasoning_content"] == "hm ok"
    assert message["tool_calls"] == [
        {"type": "function", "id": "c1", "function": {"name": "fs_read", "arguments": '{"path":"a"}'}}
    ]
    assert read["choices"][0]["finish_reason"] == "tool_calls" and read["usage"]["completion_tokens"] == 3


def test_a_plain_body_is_parsed_or_kept_as_text() -> None:
    from thursday_llm.stream_reader import read_response

    assert read_response('{"error": {"message": "no"}}') == {"error": {"message": "no"}}
    assert read_response("Bad gateway") == "Bad gateway" and read_response("") is None


async def test_idle_unload_and_card_settings_are_saved_per_agent_and_zero_means_never() -> None:
    from thursday_llm.overrides import LlmOverrides, LoadOverrides
    from thursday_llm.runtime import LlmRuntime, config_from_env

    saved: dict = {}
    rt = LlmRuntime(
        lambda: config_from_env(ProviderKind.LMSTUDIO, "http://127.0.0.1:1234", "m", None, 60.0, idle_unload_minutes=5),
        lambda: saved or None,
        saved.update,
    )
    assert rt.config.idle_unload_minutes == 5
    await rt.update(LlmOverrides(idle_unload_minutes=0, load=LoadOverrides(gpu_layers="all", gpu_split="2,1")))
    assert rt.config.idle_unload_minutes == 0, "0 is a choice (never), not 'unset'"
    assert rt.config.load.gpu_layers == "all" and rt.config.load.gpu_split == "2,1"
    assert "gpu_layers" not in rt.config.load.as_request(), "LM Studio is not sent llama.cpp's settings"
    await rt.update(LlmOverrides(idle_unload_minutes=None))
    assert rt.config.idle_unload_minutes == 5, "null returns to the .env value"
    assert await rt.hear(b"wav") is None, "LM Studio cannot hear"
    with pytest.raises(ValueError):
        LoadOverrides(gpu_layers="lots")
    with pytest.raises(ValueError):
        LoadOverrides(gpu_split="3")
    await rt.provider.aclose()


async def test_each_provider_remembers_its_own_model_and_address() -> None:
    from thursday_llm.overrides import LlmOverrides
    from thursday_llm.providers import NO_MODEL, ProviderError
    from thursday_llm.runtime import LlmRuntime, config_from_env

    saved: dict = {}
    rt = LlmRuntime(
        lambda: config_from_env(ProviderKind.LMSTUDIO, "http://127.0.0.1:1234", "google/gemma-12b", None, 60.0),
        lambda: saved or None,
        saved.update,
    )
    await rt.update(LlmOverrides(provider=ProviderKind.LLAMACPP))
    assert rt.config.model == "" and rt.config.base_url == "", "an LM Studio model name means nothing to llama.cpp"
    await rt.update(LlmOverrides(model="gemma/gemma-12b-Q4.gguf"))
    await rt.update(
        LlmOverrides(provider=ProviderKind.OPENAI_COMPATIBLE, base_url="https://api.example.com", model="big")
    )
    assert (rt.config.model, rt.config.base_url) == ("big", "https://api.example.com"), "chosen in the same change"
    assert rt.describe()["remembered"]["llamacpp"] == {"model": "gemma/gemma-12b-Q4.gguf"}

    await rt.update(LlmOverrides(provider=ProviderKind.LLAMACPP))
    assert rt.config.model == "gemma/gemma-12b-Q4.gguf", "back on llama.cpp: its own model again"
    await rt.update(LlmOverrides(provider=ProviderKind.LMSTUDIO))
    assert (rt.config.model, rt.config.base_url) == ("google/gemma-12b", "http://127.0.0.1:1234"), "the .env values"
    await rt.update(LlmOverrides(provider=ProviderKind.OPENAI_COMPATIBLE))
    assert (rt.config.model, rt.config.base_url) == ("big", "https://api.example.com")

    await rt.update(LlmOverrides(model=None, base_url=None))
    assert rt.config.model == "", "nothing chosen for this provider"
    with pytest.raises(ProviderError, match="No model is chosen"):
        await rt.provider.ensure_loaded()
    assert NO_MODEL.startswith("No model is chosen")

    await rt.update(LlmOverrides.model_validate({"remembered": {"lmstudio": {"model": "planted"}}}))
    assert (
        "lmstudio" not in rt.describe()["remembered"]
        or rt.describe()["remembered"]["lmstudio"].get("model") != "planted"
    )
    await rt.provider.aclose()


async def test_the_checks_before_one_call_share_one_request_to_lm_studio() -> None:
    fake = FakeLmStudio(loaded=True)
    asked = {"n": 0}

    def counting(request: httpx.Request) -> httpx.Response:
        asked["n"] += request.url.path == "/api/v1/models"
        return fake.handler(request)

    client = httpx.AsyncClient(
        base_url="http://lm", headers={"Authorization": "Bearer k"}, transport=httpx.MockTransport(counting)
    )
    lm = LmStudioProvider(config(), client)
    assert await lm.reachable() and (await lm.ensure_loaded()).adopted and (await lm.ensure_loaded()).adopted
    assert asked["n"] == 1, "reachable, loaded, and loaded again a moment later: one request"
    await lm.unload()
    assert (await lm.ensure_loaded()).adopted is False, "after an unload the list is asked for again, not remembered"


async def test_a_cloud_endpoint_is_not_asked_whether_it_is_up_before_every_turn() -> None:
    from thursday_llm.providers import OpenAICompatibleProvider
    from thursday_llm.providers import openai_compatible as module

    state = {"up": True, "asked": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["asked"] += 1
        if not state["up"]:
            raise httpx.ConnectError("down")
        return httpx.Response(200, json={"data": [{"id": "gpt"}]})

    cloud = OpenAICompatibleProvider(
        config(provider=ProviderKind.OPENAI_COMPATIBLE),
        httpx.AsyncClient(base_url="http://cloud", transport=httpx.MockTransport(handler)),
    )
    assert await cloud.reachable() and await cloud.reachable() and state["asked"] == 1
    state["up"] = False
    cloud._reachable = (cloud._reachable[0] - module.REACHABLE_FOR_SECONDS - 1, True)  # pyright: ignore[reportOptionalSubscript]
    assert not await cloud.reachable() and state["asked"] == 2, "the answer is asked for again once it is old"
    state["up"] = True
    assert not await cloud.reachable() and state["asked"] == 2, "a no is kept only for a few seconds"
    cloud._reachable = (cloud._reachable[0] - module.UNREACHABLE_FOR_SECONDS - 1, False)  # pyright: ignore[reportOptionalSubscript]
    assert await cloud.reachable() and state["asked"] == 3
