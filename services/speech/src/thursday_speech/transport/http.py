"""HTTP surface of the speech service (localhost, service token). The gateway is its only caller."""

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


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_SPEAK_CHARS * 4)
    voice: str | None = Field(default=None, max_length=40)


def build_router(speech: SpeechService, auth: Callable[..., Awaitable[None]]) -> APIRouter:
    r = APIRouter(prefix="/v1", dependencies=[Depends(auth)])

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
