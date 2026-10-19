"""Composition root: settings, the two engines, routes, health."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI
from pydantic import Field
from pydantic_settings import SettingsConfigDict
from thursday_contracts.health import ServiceName
from thursday_runtime.auth import ServiceTokenAuth
from thursday_runtime.health import build_health_router
from thursday_runtime.log_setup import configure_logging
from thursday_runtime.paths import log_dir, service_data_dir
from thursday_runtime.serve import serve
from thursday_runtime.settings import CommonSettings, env_file

from thursday_speech import __version__
from thursday_speech.application.speech import Decoder, Speaker, SpeechService, Transcriber
from thursday_speech.transport.http import build_router

SERVICE = ServiceName.SPEECH


class SpeechSettings(CommonSettings):
    model_config = SettingsConfigDict(
        env_file=env_file(), env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )

    speech_stt_model: str = Field(default="small", max_length=60)  # a faster-whisper model size or name
    # A speech engine nobody has used for this many minutes is dropped from memory; 0 keeps it loaded.
    speech_idle_unload_minutes: float = Field(default=5, ge=0, le=1440)


def create_app(
    settings: SpeechSettings | None = None,
    transcriber: Transcriber | None = None,
    speaker: Speaker | None = None,
    decoder: Decoder | None = None,
) -> FastAPI:
    settings = settings or SpeechSettings()
    if transcriber is None or speaker is None:
        from thursday_speech.infrastructure.engines import KokoroSpeaker, WhisperTranscriber

        transcriber = transcriber or WhisperTranscriber(settings.speech_stt_model)
        speaker = speaker or KokoroSpeaker(service_data_dir(SERVICE.value, settings.thursday_data_dir) / "models")
    if decoder is None:
        from thursday_speech.infrastructure.decode import to_wav as decoder
    speech = SpeechService(transcriber, speaker, decoder)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        stop = asyncio.Event()
        idle = asyncio.create_task(speech.idle_loop(stop, settings.speech_idle_unload_minutes), name="idle-unload")
        try:
            yield
        finally:
            stop.set()
            await idle

    app = FastAPI(title="Thursday speech", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.include_router(build_health_router(SERVICE, __version__))
    app.include_router(build_router(speech, ServiceTokenAuth(settings.thursday_service_token)))

    @app.get("/metrics")
    async def own_metrics() -> dict[str, Any]:
        return {
            "transcriptions": speech.transcriptions,
            "spoken": speech.spoken,
            "stt_seconds": speech.last_transcribe_seconds,
            "tts_seconds": speech.last_speak_seconds,
            "stt_loaded": bool(getattr(transcriber, "loaded", True)),
            "tts_loaded": bool(getattr(speaker, "loaded", True)),
        }

    return app


def run() -> None:
    settings = SpeechSettings()
    configure_logging(SERVICE.value, log_dir(settings.thursday_data_dir), settings.log_level)
    serve(create_app(settings), settings.speech_port, settings.log_level)
