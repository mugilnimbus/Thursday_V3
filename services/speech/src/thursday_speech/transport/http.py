"""HTTP surface of the speech service (localhost, service token). The gateway is its only caller."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from thursday_speech.application.speech import (
    MAX_AUDIO_BYTES,
    MAX_SPEAK_CHARS,
    EngineUnavailable,
    SpeechError,
    SpeechService,
)

log = logging.getLogger(__name__)


class WarmIn(BaseModel):
    listen: bool = True
    speak: bool = False


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_SPEAK_CHARS * 4)
    voice: str | None = Field(default=None, max_length=40)


def build_router(speech: SpeechService, auth: Callable[..., Awaitable[None]]) -> APIRouter:
    r = APIRouter(prefix="/v1", dependencies=[Depends(auth)])
    warming: set[asyncio.Task[None]] = set()

    @r.post("/warm", status_code=202)
    async def warm(body: WarmIn) -> dict[str, Any]:
        """Start loading the engines a spoken turn is about to need, and answer at once."""

        async def load() -> None:
            try:
                await speech.warm(listen=body.listen, speak=body.speak)
            except EngineUnavailable as exc:
                log.warning("warm-up failed: %s", exc)

        task = asyncio.get_running_loop().create_task(load())
        warming.add(task)
        task.add_done_callback(warming.discard)
        return {"warming": True}

    @r.post("/transcribe")
    async def transcribe(request: Request) -> dict[str, Any]:
        """Body: the recorded audio exactly as the client captured it (webm, m4a, wav)."""
        declared = int(request.headers.get("content-length") or 0)
        if declared > MAX_AUDIO_BYTES:
            raise HTTPException(413, "the recording is too long")
        audio = await request.body()
        try:
            result = await speech.transcribe(audio)
        except SpeechError as exc:
            raise HTTPException(422, str(exc)) from exc
        except EngineUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        return {
            "text": result.text,
            "language": result.language,
            "audio_seconds": result.audio_seconds,
            "seconds": result.seconds,
        }

    @r.post("/decode")
    async def decode(request: Request) -> Response:
        """Body: a recording in any common format. Returns it as WAV (16 kHz, mono), for a model that hears."""
        if int(request.headers.get("content-length") or 0) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "the recording is too long")
        try:
            wav, seconds = await speech.to_wav(await request.body())
        except SpeechError as exc:
            raise HTTPException(422, str(exc)) from exc
        except EngineUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        return Response(
            wav,
            media_type="audio/wav",
            headers={"X-Audio-Seconds": str(round(seconds, 2)), "Cache-Control": "no-store"},
        )

    @r.post("/speak")
    async def speak(body: SpeakIn) -> Response:
        try:
            result = await speech.speak(body.text, body.voice)
        except SpeechError as exc:
            raise HTTPException(422, str(exc)) from exc
        except EngineUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        headers = {"X-Audio-Seconds": str(result.audio_seconds), "X-Voice": result.voice, "Cache-Control": "no-store"}
        return Response(result.wav, media_type="audio/wav", headers=headers)

    @r.get("/voices")
    async def voices() -> dict[str, Any]:
        try:
            return {"voices": await speech.voices()}
        except EngineUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc

    return r
