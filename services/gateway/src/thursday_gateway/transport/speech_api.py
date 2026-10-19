"""Speech for clients (`/v1/speech`): the gateway forwards to the local speech service.

- `POST /v1/speech/transcribe`: body is the recorded audio; returns the text. When the voice agent's model can
  hear, it writes the words down itself (`by: voice_model`); otherwise, and whenever that fails, the speech
  service's speech-to-text does (`by: whisper`).
- `POST /v1/speech/speak`: `{text, voice?}`; returns WAV audio.
- `GET /v1/speech`: whether speech is available, and the voices.
- `POST /v1/speech/warm`: `{speak?, listen?}`; the microphone was pressed (or, with `listen` false, a typed
  message will be read aloud), so start loading what the turn will need.
Audio is never stored by the gateway; only the text that the user then sends becomes a message.
"""

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from thursday_gateway.application.errors import AgentRefused, AgentUnavailable
from thursday_gateway.application.ports import SpeechService
from thursday_gateway.application.talk_warmup import TalkWarmup
from thursday_gateway.domain.model import InvalidInput

MAX_AUDIO_BYTES = 15 * 1024 * 1024


class Hearer(Protocol):
    async def hear(self, wav: bytes) -> dict[str, Any] | None: ...


class WarmIn(BaseModel):
    speak: bool = False  # replies are read aloud, so the voice is needed too
    listen: bool = True  # false for a typed message: nothing has to be heard


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    voice: str | None = Field(default=None, max_length=40)


def build_speech_router(
    speech: SpeechService,
    auth: Callable[..., Awaitable[None]],
    voice: Hearer | None = None,
    warmup: TalkWarmup | None = None,
) -> APIRouter:
    r = APIRouter(prefix="/v1/speech", dependencies=[Depends(auth)])

    @r.get("")
    async def status() -> dict[str, Any]:
        try:
            return {"available": True, "voices": (await speech.call("GET", "/voices")).json()["voices"]}
        except (AgentUnavailable, AgentRefused) as exc:
            return {"available": False, "voices": [], "detail": str(exc)}

    @r.post("/transcribe")
    async def transcribe(request: Request) -> Any:
        if int(request.headers.get("content-length") or 0) > MAX_AUDIO_BYTES:
            raise InvalidInput("the recording is too long")
        audio = await request.body()
        if not audio:
            raise InvalidInput("the recording is empty")
        heard = await by_voice_model(audio)
        if heard is not None:
            return heard
        return {**(await speech.call("POST", "/transcribe", content=audio)).json(), "by": "whisper"}

    async def by_voice_model(audio: bytes) -> dict[str, Any] | None:
        """The recording as WAV, heard by the voice model. None for any reason it cannot: the caller falls back."""
        if voice is None:
            return None
        try:
            wav = (await speech.call("POST", "/decode", content=audio)).content
        except (AgentUnavailable, AgentRefused):
            return None
        return await voice.hear(wav)

    @r.post("/warm", status_code=202)
    async def warm(body: WarmIn) -> dict[str, Any]:
        if warmup is not None:
            warmup.start(body.speak, body.listen)
        return {"warming": warmup is not None}

    @r.post("/speak")
    async def speak(body: SpeakIn) -> Response:
        upstream = await speech.call("POST", "/speak", json=body.model_dump(exclude_none=True))
        return Response(upstream.content, media_type="audio/wav", headers={"Cache-Control": "no-store"})

    return r
