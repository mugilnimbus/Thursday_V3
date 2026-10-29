"""The built-in llama.cpp provider, against a stand-in `llama-server` (a tiny script), so no model is loaded."""

import sys
import textwrap
from pathlib import Path

import pytest
from thursday_llm import gpu_plan
from thursday_llm.config import LlamaCppConfig, LlmConfig, LoadParameters, ProviderKind
from thursday_llm.providers import LlamaCppProvider, ProviderError
from thursday_llm.runtime import LlmRuntime

FAKE_SERVER = textwrap.dedent(
    """
    import json, sys
    from http.server import BaseHTTPRequestHandler, HTTPServer

    argv = sys.argv[1:]
    if any("crash" in a for a in argv):
        print("error: failed to load the model", flush=True)
        sys.exit(3)
    port = int(argv[argv.index("--port") + 1])
    key = argv[argv.index("--api-key") + 1]
    ctx = int(argv[argv.index("-c") + 1])
    audio = "--mmproj" in argv
    heard = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            system, user = body["messages"]
            part = user["content"][0]
            wav = part["type"] == "input_audio" and part["input_audio"]["format"] == "wav"
            said = "turn on the lights" if wav else ""
            ok = self.headers.get("Authorization") == "Bearer " + key
            ok = ok and body["chat_template_kwargs"] == {"enable_thinking": False}
            ok = ok and system["role"] == "system" and len(user["content"]) == 1
            data = json.dumps({"choices": [{"message": {"content": "  " + said + " "}}]}).encode()
            self.send_response(200 if ok else 401); self.send_header("Content-Length", str(len(data)))
            self.end_headers(); self.wfile.write(data)
        def do_GET(self):
            if self.path == "/health":
                body = {"status": "ok"}
            elif self.path == "/props" and self.headers.get("Authorization") == "Bearer " + key:
                body = {"default_generation_settings": {"n_ctx": ctx}, "modalities": {"vision": audio, "audio": audio}}
            else:
                self.send_response(401); self.end_headers(); return
            data = json.dumps(body).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(data)))
            self.end_headers(); self.wfile.write(data)

    HTTPServer(("127.0.0.1", port), H).serve_forever()
    """
)


class FakeLlamaCpp(LlamaCppProvider):
    """Runs the stand-in script instead of llama-server, and remembers what it was asked to run."""

    script: Path
    runs: list[list[str]]

    def _command(self, arguments: list[str]) -> list[str]:
        self.runs.append(arguments)
        return [sys.executable, str(self.script), *arguments[1:]]


@pytest.fixture
def folders(tmp_path: Path) -> dict[str, Path]:
    server = tmp_path / "llama"
    server.mkdir()
    (server / ("llama-server.exe" if sys.platform == "win32" else "llama-server")).write_bytes(b"")
    models = tmp_path / "models"
    (models / "gemma").mkdir(parents=True)
    (models / "gemma" / "gemma-e4b-Q4.gguf").write_bytes(b"x" * 100)
    (models / "gemma" / "mmproj-gemma-e4b-BF16.gguf").write_bytes(b"y" * 10)
    (models / "plain").mkdir()
    (models / "plain" / "text-only.gguf").write_bytes(b"z" * 50)
    (models / "plain" / "crash-me.gguf").write_bytes(b"z" * 5)
    script = tmp_path / "fake_server.py"
    script.write_text(FAKE_SERVER, encoding="utf-8")
    return {"server": server, "models": models, "script": script, "logs": tmp_path / "logs"}


def make(
    folders: dict[str, Path], model: str = "gemma/gemma-e4b-Q4.gguf", load: LoadParameters | None = None
) -> FakeLlamaCpp:
    config = LlmConfig(
        ProviderKind.LLAMACPP,
        "",
        model,
        load=load or LoadParameters(),
        llamacpp=LlamaCppConfig(str(folders["server"]), str(folders["models"]), None, str(folders["logs"]), "test"),
    )
    provider = FakeLlamaCpp(config)
    provider.script = folders["script"]
    provider.runs = []
    return provider


async def test_the_models_folder_is_listed_with_projectors_and_without_projector_files(folders) -> None:
    provider = make(folders)
    models = {m.key: m for m in await provider.list_models()}
    assert sorted(models) == ["gemma/gemma-e4b-Q4.gguf", "plain/crash-me.gguf", "plain/text-only.gguf"]
    assert models["gemma/gemma-e4b-Q4.gguf"].projector == "mmproj-gemma-e4b-BF16.gguf"
    assert models["plain/text-only.gguf"].projector is None and models["plain/text-only.gguf"].size_bytes == 50
    assert not any(m.loaded for m in models.values())


async def test_an_unset_models_folder_or_server_folder_says_what_to_do() -> None:
    provider = FakeLlamaCpp(LlmConfig(ProviderKind.LLAMACPP, "", "x.gguf"))
    with pytest.raises(ProviderError, match="folder that holds your model files"):
        await provider.list_models()
    assert not await provider.reachable()


async def test_nothing_starts_until_a_model_is_loaded(folders) -> None:
    provider = make(folders)
    assert provider.runs == [] and not provider.alive and provider.loaded is None and provider.endpoint is None
    await provider.aclose()


async def test_loading_starts_one_server_with_the_chosen_settings_and_adopts_it_next_time(folders) -> None:
    provider = make(
        folders,
        load=LoadParameters(
            context_length=4096,
            flash_attention=True,
            offload_kv_cache_to_gpu=False,
            eval_batch_size=512,
            moe_cpu_layers=3,
        ),
    )
    try:
        first = await provider.ensure_loaded()
        assert not first.adopted and first.context_length == 4096 and provider.alive
        assert provider.modalities == {"vision": True, "audio": True}, "a projector beside the model means it can hear"
        args = provider.runs[0]
        for flag, value in (
            ("-c", "4096"),
            ("-fa", "on"),
            ("-b", "512"),
            ("-ub", "512"),
            ("--n-cpu-moe", "3"),
            ("--host", "127.0.0.1"),
        ):
            assert args[args.index(flag) + 1] == value
        assert "--no-kv-offload" in args and "--jinja" in args and "--mmproj" in args and provider.api_key in args
        assert "-ngl" not in args and "--tensor-split" not in args, (
            "left unset, llama.cpp itself fits the layers to the cards"
        )
        second = await provider.ensure_loaded()
        assert second.adopted and len(provider.runs) == 1, "no second process"
        assert [m.loaded for m in await provider.list_models()] == [True, False, False]
    finally:
        await provider.aclose()


async def test_unloading_stops_the_server_and_the_next_use_starts_a_fresh_one(folders) -> None:
    provider = make(folders)
    try:
        await provider.ensure_loaded()
        process = provider._process
        await provider.unload()
        assert process is not None and process.poll() is not None, "the process is gone, so the GPU is free"
        assert not provider.alive and provider.endpoint is None and provider.loaded is None
        await provider.ensure_loaded()
        assert len(provider.runs) == 2
    finally:
        await provider.aclose()


async def test_reload_restarts_with_new_settings(folders) -> None:
    provider = make(folders, load=LoadParameters(context_length=2048))
    try:
        await provider.ensure_loaded()
        again = await provider.reload(LoadParameters(context_length=8192))
        assert again.context_length == 8192 and len(provider.runs) == 2
    finally:
        await provider.aclose()


async def test_a_model_outside_the_folder_is_refused(folders) -> None:
    provider = make(folders, model="../fake_server.py")
    with pytest.raises(ProviderError, match="not in the models folder"):
        await provider.ensure_loaded()
    assert provider.runs == []


async def test_a_server_that_dies_while_loading_reports_why(folders) -> None:
    provider = make(folders, model="plain/crash-me.gguf")
    with pytest.raises(ProviderError, match=r"code 3.*failed to load the model"):
        await provider.ensure_loaded()
    assert not provider.alive


async def test_the_chat_client_exists_only_once_the_server_runs_and_points_at_it(folders) -> None:
    provider = make(folders)
    runtime = LlmRuntime(lambda: provider._config, lambda: None, lambda _: None, fixed_provider=provider)
    try:
        with pytest.raises(RuntimeError, match="load the model first"):
            _ = runtime.chat
        await provider.ensure_loaded()
        assert str(provider.endpoint) in str(runtime.chat.openai_api_base)
        assert runtime.describe()["hears_audio"] is True
    finally:
        await provider.aclose()


async def test_the_cards_layers_and_split_can_be_chosen(folders) -> None:
    provider = make(folders, load=LoadParameters(gpu_layers="24", gpu_split="3,1"))
    try:
        await provider.ensure_loaded()
        args = provider.runs[0]
        for flag, value in (("-ngl", "24"), ("--tensor-split", "3,1")):
            assert args[args.index(flag) + 1] == value
    finally:
        await provider.aclose()


async def test_a_running_server_is_recorded_so_a_leftover_can_be_stopped(folders) -> None:
    provider = make(folders)
    record = folders["logs"] / "llama-test.pid"
    try:
        await provider.ensure_loaded()
        assert provider._process is not None and record.read_text() == str(provider._process.pid)
        await provider.unload()
        assert not record.exists(), "a server stopped properly leaves no record"
    finally:
        await provider.aclose()


async def test_a_model_that_hears_writes_down_a_recording_and_a_text_model_says_it_cannot(folders) -> None:
    hearing = make(folders)
    deaf = make(folders, model="plain/text-only.gguf")
    try:
        assert await hearing.hear(b"RIFFwav") == "turn on the lights", "loads the model, then asks it"
        assert hearing.alive
        assert await deaf.hear(b"RIFFwav") is None, "no projector, so no audio: the caller uses speech-to-text"
    finally:
        await hearing.aclose()
        await deaf.aclose()


async def test_an_idle_model_is_unloaded_and_one_in_use_never_is(folders) -> None:
    import dataclasses

    provider = make(folders)
    config = dataclasses.replace(provider._config, idle_unload_minutes=5)
    runtime = LlmRuntime(lambda: config, lambda: None, lambda _: None, fixed_provider=provider)
    try:
        assert not await runtime.unload_if_idle(), "nothing is loaded yet"
        async with runtime.use():
            await provider.ensure_loaded()
            runtime._last_used -= 3600
            assert not await runtime.unload_if_idle(), "a model in use stays, however long the call takes"
        assert runtime.idle_seconds < 5, "the idle time starts when the call ends"
        assert not await runtime.unload_if_idle() and provider.alive
        runtime._last_used -= 301
        assert runtime.describe()["idle_seconds"] >= 300
        assert await runtime.unload_if_idle() and not provider.alive, "five minutes without use frees the hardware"
        assert runtime.describe()["loaded"] is None and runtime.describe()["idle_unload_minutes"] == 5

        await provider.ensure_loaded()
        runtime.config = dataclasses.replace(config, idle_unload_minutes=0)
        runtime._last_used -= 36000
        assert not await runtime.unload_if_idle() and provider.alive, "0 keeps the model loaded"
        assert await runtime.hear(b"RIFFwav") == "turn on the lights"
    finally:
        await provider.aclose()


# What llama.cpp's own tools print (build b11146), kept short.
DEVICES = """Available devices:
  CUDA0: NVIDIA GeForce RTX 3080 Ti (12287 MiB, 11098 MiB free)
  CUDA1: NVIDIA GeForce RTX 3080 Ti (12287 MiB, 11098 MiB free)
"""
FITS_ONE = """fit: projected to use 3593 MiB of device memory vs. 11098 MiB of free device memory
fit: will leave 7504 >= 1970 MiB of free device memory, no changes needed
"""
TOO_BIG_FOR_ONE = """fit: projected to use 14908 MiB of device memory vs. 11098 MiB of free device memory
fit: cannot meet free memory target of 1024 MiB, need to reduce device memory by 4834 MiB
"""
FITS_TWO = """fit: projected to use 15252 MiB of device memory vs. 22196 MiB of free device memory
fit: targets for free memory can be met on all devices, no changes needed
"""
TOO_FULL = """fit:   - CUDA0 (NVIDIA GeForce RTX 3080 Ti):  12287 total,  10308 used,    789 free
fit: projected to use 15252 MiB of device memory vs. 22196 MiB of free device memory
"""


def test_the_tools_output_is_read_into_cards_needs_and_whether_it_fits() -> None:
    cards = gpu_plan.parse_devices(DEVICES)
    assert [(c.name, c.index, c.label, c.total_mb, c.free_mb) for c in cards] == [
        ("CUDA0", 0, "NVIDIA GeForce RTX 3080 Ti", 12287, 11098),
        ("CUDA1", 1, "NVIDIA GeForce RTX 3080 Ti", 12287, 11098),
    ]
    assert gpu_plan.parse_fit(FITS_ONE) == gpu_plan.Fit(3593, True)
    assert gpu_plan.parse_fit(TOO_BIG_FOR_ONE) == gpu_plan.Fit(14908, False)
    assert gpu_plan.parse_fit(FITS_TWO) == gpu_plan.Fit(15252, True)
    assert gpu_plan.parse_fit(TOO_FULL) == gpu_plan.Fit(15252, False)
    assert gpu_plan.parse_fit("nothing useful") == gpu_plan.Fit(None, False)


def test_cards_are_filled_in_the_chosen_order_and_only_as_many_as_needed() -> None:
    cards = gpu_plan.parse_devices(DEVICES)
    assert [c.index for c in gpu_plan.in_order(cards, [1])] == [1, 0], "card 1 first, then the rest by number"
    assert [c.index for c in gpu_plan.in_order(cards, [7, 0, 0])] == [0, 1], "a card that is not there is ignored"
    assert gpu_plan.fill(3593, cards, [1024, 1024]) == [3593], "it fits on the first card: the second is not used"
    assert gpu_plan.fill(15252, cards, [2163, 1024]) == [8935, 6317], "the first card is filled, the rest goes on"
    assert gpu_plan.fill(30000, cards, [1024, 1024]) is None, "more than both cards hold: left to llama.cpp"
    assert gpu_plan.shifted([8935, 6317]) == [8020, 7232] and sum(gpu_plan.shifted([8935, 6317])) == 15252


class PlannedLlamaCpp(FakeLlamaCpp):
    """Answers for llama.cpp's own tools, so the plan can be tested without graphics cards."""

    answers: list[str]
    tools: list[list[str]]

    def _run_tool(self, command: list[str], stop_at: str | None = None) -> str:
        self.tools.append(command)
        return DEVICES if "--list-devices" in command else self.answers.pop(0)


def planned(folders, answers: list[str], load: LoadParameters, gpu: int | None = None) -> PlannedLlamaCpp:
    config = LlmConfig(
        ProviderKind.LLAMACPP,
        "",
        "gemma/gemma-e4b-Q4.gguf",
        load=load,
        llamacpp=LlamaCppConfig(str(folders["server"]), str(folders["models"]), gpu, str(folders["logs"]), "test"),
    )
    (folders["server"] / ("llama-fit-params.exe" if sys.platform == "win32" else "llama-fit-params")).write_bytes(b"")
    provider = PlannedLlamaCpp(config)
    provider.script = folders["script"]
    provider.runs = []
    provider.tools = []
    provider.answers = answers
    return provider


def value(args: list[str], flag: str) -> str | None:
    return args[args.index(flag) + 1] if flag in args else None


async def test_a_model_that_fits_the_first_card_goes_on_that_card_alone(folders) -> None:
    provider = planned(folders, [FITS_ONE], LoadParameters(gpu_priority="1", gpu_split="1,1"))
    try:
        await provider.ensure_loaded()
        args = provider.runs[0]
        assert value(args, "--device") == "CUDA1" and "--tensor-split" not in args, "the chosen card, and only it"
        assert provider.placement == "all on card 1"
        fit = provider.tools[1]
        assert value(fit, "--device") == "CUDA1" and value(fit, "-c") == value(args, "-c"), "asked about the same load"
        assert int(value(fit, "--fit-target") or 0) >= gpu_plan.MARGIN_MB
    finally:
        await provider.aclose()


async def test_a_model_too_large_for_one_card_fills_the_first_and_puts_the_rest_on_the_next(folders) -> None:
    provider = planned(folders, [TOO_BIG_FOR_ONE, TOO_FULL, FITS_TWO], LoadParameters(gpu_priority="0"))
    try:
        await provider.ensure_loaded()
        args = provider.runs[0]
        assert value(args, "--device") == "CUDA0,CUDA1"
        first, second = (int(n) for n in (value(args, "--tensor-split") or "").split(","))
        assert first > second and first + second == round(14908 * gpu_plan.HEADROOM), "card 0 holds the larger part"
        assert len(provider.tools) == 4, "the cards, one card alone, a plan that was too full, and the plan that fits"
        assert "card 0:" in provider.placement and "card 1:" in provider.placement
    finally:
        await provider.aclose()


async def test_when_no_order_works_or_one_card_is_chosen_llama_cpp_decides(folders) -> None:
    hopeless = planned(folders, [TOO_BIG_FOR_ONE] + [TOO_FULL] * 4, LoadParameters(gpu_priority="0", gpu_split="1,1"))
    pinned = planned(folders, [], LoadParameters(gpu_priority="0", gpu_split="1,1"), gpu=1)
    try:
        await hopeless.ensure_loaded()
        assert "--device" not in hopeless.runs[0] and "--tensor-split" not in hopeless.runs[0]
        assert hopeless.placement == ""
        await pinned.ensure_loaded()
        assert pinned.tools == [], "one card chosen: there is no order to fill"
        assert value(pinned.runs[0], "--tensor-split") == "1,1"
    finally:
        await hopeless.aclose()
        await pinned.aclose()
