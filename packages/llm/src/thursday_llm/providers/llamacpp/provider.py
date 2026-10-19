"""The built-in llama.cpp provider: it owns one `llama-server` process and the model that process serves."""

import asyncio
import contextlib
import logging
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from thursday_llm import gpu_plan
from thursday_llm.config import LlmConfig, LoadParameters
from thursday_llm.providers.base import LoadedModel, ModelInfo, ProviderError
from thursday_llm.providers.llamacpp import files, hearing, placement
from thursday_llm.providers.llamacpp.arguments import server_arguments

log = logging.getLogger(__name__)
START_TIMEOUT_SECONDS = 300.0


class LlamaCppProvider:
    """The built-in llama.cpp: one `llama-server` process per agent, started on load and stopped on unload.

    Nothing starts until `ensure_loaded` (or `reload`) is called, so a cold Thursday holds no GPU memory. Unloading
    stops the process, which frees the GPU completely. The server listens on 127.0.0.1 only, on a free port, and
    asks for a random key that only this provider and its chat client know.
    """

    def __init__(self, config: LlmConfig, client: httpx.AsyncClient | None = None) -> None:
        self._config = config
        self._client = client or httpx.AsyncClient(timeout=15)
        self._lock = asyncio.Lock()
        self._process: subprocess.Popen | None = None
        self._started_for: tuple | None = None
        self._loaded: LoadedModel | None = None
        self._load: LoadParameters | None = None
        self.endpoint: str | None = None
        self.api_key = ""
        self.modalities: dict | None = None
        self.cards: list[dict[str, object]] = []  # the graphics cards llama.cpp sees, once it has been asked
        self.placement = ""  # how the last load was placed on the cards, in words, for the log and Settings

    @property
    def supports_lifecycle(self) -> bool:
        return True

    # --- what is available -----------------------------------------------------------------------------------
    @property
    def installed(self) -> bool:
        try:
            files.server_exe(self._config.llamacpp.server_dir)
        except ProviderError:
            return False
        return True

    async def list_models(self) -> list[ModelInfo]:
        loaded_key = self._started_for[0] if self._started_for and self.alive else None
        return await asyncio.to_thread(files.scan, self._config.llamacpp.models_dir, loaded_key)

    # --- which card gets what --------------------------------------------------------------------------------
    def _fills_in_order(self, load: LoadParameters) -> bool:
        """Filling the cards in order only means something when more than one card may be used."""
        return bool(load.gpu_priority) and self._config.llamacpp.gpu is None

    def _run_tool(self, command: list[str], stop_at: str | None = None) -> str:
        """Run one of llama.cpp's own tools; a test replaces this to answer without graphics cards."""
        return placement.run_tool(command, placement.environment(self._config.llamacpp.gpu), stop_at)

    async def _cards(self, exe: Path) -> list[gpu_plan.Device]:
        devices = await placement.cards(exe, self._run_tool)
        self.cards = [{"index": d.index, "name": d.label, "total_mb": d.total_mb} for d in devices]
        return devices

    async def _placement(self, exe: Path, model: Path, load: LoadParameters) -> list[str]:
        """Arguments that fill the cards in the chosen order. Empty when llama.cpp is left to spread the model."""
        self.placement = ""
        fitter = placement.fitter_beside(exe)
        if fitter is None:
            log.warning("llama-fit-params is not in the llama.cpp folder; the cards are filled as llama.cpp decides")
            return []
        projector_mb = await asyncio.to_thread(files.projector_megabytes, model)
        plan = await placement.fill_in_order(fitter, model, load, await self._cards(exe), projector_mb, self._run_tool)
        self.placement = plan.words
        return plan.arguments

    # --- the process -----------------------------------------------------------------------------------------
    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _command(self, arguments: list[str]) -> list[str]:
        """The command line to run; a test replaces this to start a stand-in server."""
        return arguments

    def _file(self, suffix: str) -> Path:
        """This agent's log or pid file, beside the services' own logs."""
        return Path(self._config.llamacpp.log_dir or ".") / f"llama-{self._config.llamacpp.name}.{suffix}"

    def _spawn(self, arguments: list[str]) -> subprocess.Popen:
        self._file("log").parent.mkdir(parents=True, exist_ok=True)
        env = placement.environment(self._config.llamacpp.gpu)
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0  # type: ignore[attr-defined]
        with open(self._file("log"), "ab") as out:
            process = subprocess.Popen(  # noqa: S603 - a fixed argument list, no shell; the paths are the owner's
                self._command(arguments), stdout=out, stderr=out, stdin=subprocess.DEVNULL, env=env, creationflags=flags
            )
        # Recorded so the launcher can stop this server if the agent dies without stopping it.
        with contextlib.suppress(OSError):
            self._file("pid").write_text(str(process.pid), encoding="utf-8")
        return process

    async def _stop(self) -> None:
        process, self._process = self._process, None
        self._started_for = self._loaded = None
        self.endpoint = self.modalities = None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, 10)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait, 10)
        with contextlib.suppress(OSError):
            self._file("pid").unlink(missing_ok=True)

    def _log_tail(self) -> str:
        try:
            lines = self._file("log").read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        return " | ".join(line.strip() for line in lines[-4:] if line.strip())[-400:]

    async def _start(self, load: LoadParameters) -> LoadedModel:
        started = time.perf_counter()
        exe = files.server_exe(self._config.llamacpp.server_dir)
        model = files.resolve(self._config.llamacpp.models_dir, self._config.model)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.api_key = secrets.token_urlsafe(24)
        fills_in_order = self._fills_in_order(load)
        arguments = server_arguments(exe, model, port, self.api_key, load, fills_in_order=fills_in_order)
        if fills_in_order:
            arguments += await self._placement(exe, model, load)
        log.info("starting llama-server for %s with %s", self._config.model, load)
        process = await asyncio.to_thread(self._spawn, arguments)
        self._process = process
        url = f"http://127.0.0.1:{port}"
        await self._wait_until_ready(process, url)
        self.endpoint = url
        context, self.modalities = await self._props(url)
        self._started_for = (self._config.model, tuple(arguments[1:]))
        self._loaded = LoadedModel(
            self._config.model, None, context, adopted=False, load_seconds=round(time.perf_counter() - started, 1)
        )
        return self._loaded

    async def _wait_until_ready(self, process: subprocess.Popen, url: str) -> None:
        """Until the server says the model is loaded. Fails when the process stops first or takes too long."""
        deadline = time.monotonic() + START_TIMEOUT_SECONDS
        while True:
            if process.poll() is not None:
                tail = self._log_tail()
                code = process.returncode
                await self._stop()
                raise ProviderError(f"llama.cpp stopped while loading the model (code {code}). {tail}")
            try:
                if (await self._client.get(f"{url}/health", timeout=3)).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                await self._stop()
                raise ProviderError("llama.cpp did not finish loading the model in time.")
            await asyncio.sleep(0.3)

    async def _props(self, url: str) -> tuple[int | None, dict | None]:
        try:
            response = await self._client.get(f"{url}/props", headers={"Authorization": f"Bearer {self.api_key}"})
            data = response.json()
        except (httpx.HTTPError, ValueError):
            return None, None
        return (data.get("default_generation_settings") or {}).get("n_ctx"), data.get("modalities")

    # --- the provider interface ------------------------------------------------------------------------------
    async def ensure_loaded(self) -> LoadedModel:
        async with self._lock:
            load = self._load or self._config.load
            same_model = self._started_for is not None and self._started_for[0] == self._config.model
            if self.alive and self._loaded is not None and same_model:
                return LoadedModel(self._loaded.key, None, self._loaded.context_length, adopted=True)
            await self._stop()
            return await self._start(load)

    async def unload(self) -> None:
        async with self._lock:
            await self._stop()

    async def reload(self, load: LoadParameters | None = None) -> LoadedModel:
        async with self._lock:
            await self._stop()
            self._load = load or self._config.load
            return await self._start(self._load)

    async def reachable(self) -> bool:
        try:
            exe = files.server_exe(self._config.llamacpp.server_dir)
            if not self.cards:  # asked once, so Settings can name the real cards
                with contextlib.suppress(OSError, subprocess.SubprocessError):
                    await self._cards(exe)
            files.models_dir(self._config.llamacpp.models_dir)
        except ProviderError:
            return False
        return True

    @property
    def loaded(self) -> LoadedModel | None:
        return self._loaded if self.alive else None

    async def hear(self, wav: bytes) -> str | None:
        """The words spoken in a WAV clip, written down by the model itself. None when the model cannot hear.

        Loads the model if it is not loaded: only a running server says whether its model takes audio.
        """
        await self.ensure_loaded()
        if self.endpoint is None or not (self.modalities or {}).get("audio"):
            return None
        return await hearing.transcribe(self._client, self.endpoint, self.api_key, self._config.model, wav)

    async def aclose(self) -> None:
        await self._stop()
        await self._client.aclose()
