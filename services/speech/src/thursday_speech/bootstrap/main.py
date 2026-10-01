"""Composition root: settings, the two engines, routes, health."""

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
from thursday_speech.application.speech import Speaker, SpeechService, Transcriber
from thursday_speech.transport.http import build_router

SERVICE = ServiceName.SPEECH


class SpeechSettings(CommonSettings):
    model_config = SettingsConfigDict(
        env_file=env_file(), env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )

    speech_stt_model: str = Field(default="small", max_length=60)  # a faster-whisper model size or name


def create_app(
    settings: SpeechSettings | None = None, transcriber: Transcriber | None = None, speaker: Speaker | None = None
) -> FastAPI:
    settings = settings or SpeechSettings()
    if transcriber is None or speaker is None:
        from thursday_speech.infrastructure.engines import KokoroSpeaker, WhisperTranscriber

        transcriber = transcriber or WhisperTranscriber(settings.speech_stt_model)
        speaker = speaker or KokoroSpeaker(service_data_dir(SERVICE.value, settings.thursday_data_dir) / "models")
    speech = SpeechService(transcriber, speaker)

    app = FastAPI(title="Thursday speech", version=__version__, docs_url=None, redoc_url=None)
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
