"""Speech for clients (`/v1/speech`): the gateway forwards to the local speech service.

- `POST /v1/speech/transcribe`: body is the recorded audio; returns the text.
- `POST /v1/speech/speak`: `{text, voice?}`; returns WAV audio.
- `GET /v1/speech`: whether speech is available, and the voices.
Audio is never stored by the gateway; only the text that the user then sends becomes a message.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, SecretStr

from thursday_gateway.domain.model import InvalidInput
from thursday_gateway.infrastructure.agents import AgentRefused, AgentUnavailable

MAX_AUDIO_BYTES = 15 * 1024 * 1024


class SpeechClient:
    def __init__(self, base_url: str, token: SecretStr, client: httpx.AsyncClient | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(10, read=300))
        self._headers = {"Authorization": f"Bearer {token.get_secret_value()}"}

    async def call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(method, f"{self._base}/v1{path}", headers=self._headers, **kwargs)
        except httpx.HTTPError as exc:
            raise AgentUnavailable(f"the speech service is not running ({type(exc).__name__})") from exc
        if response.status_code >= 400:
            detail = response.json().get("detail", "") if "json" in response.headers.get("content-type", "") else ""
            raise AgentRefused(response.status_code, str(detail) or "the speech service refused the request")
        return response


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    voice: str | None = Field(default=None, max_length=40)


def build_speech_router(speech: SpeechClient, auth: Callable[..., Awaitable[None]]) -> APIRouter:
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
        return (await speech.call("POST", "/transcribe", content=audio)).json()

    @r.post("/speak")
    async def speak(body: SpeakIn) -> Response:
        upstream = await speech.call("POST", "/speak", json=body.model_dump(exclude_none=True))
        return Response(upstream.content, media_type="audio/wav", headers={"Cache-Control": "no-store"})

    return r
