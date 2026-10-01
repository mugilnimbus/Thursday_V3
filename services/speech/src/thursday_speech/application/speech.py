"""Speech use cases: turn a recorded clip into text, and turn a reply into audio.

The engines are behind small interfaces so the service can be tested without models, and so a
different engine can replace one later. Both engines are loaded on first use, run in a worker
thread (they are CPU-bound), and take one request at a time each.
"""

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Protocol

MAX_AUDIO_BYTES = 15 * 1024 * 1024  # about 15 minutes of compressed speech
MAX_SPEAK_CHARS = 2000
DEFAULT_VOICE = "af_heart"


class SpeechError(Exception):
    """The request cannot be served as given (bad input)."""


class EngineUnavailable(Exception):
    """An engine could not be loaded or failed while running."""


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    language: str
    audio_seconds: float
    seconds: float


@dataclass(frozen=True, slots=True)
class Speech:
    wav: bytes
    audio_seconds: float
    seconds: float
    voice: str


class Transcriber(Protocol):
    def transcribe(self, audio: bytes) -> tuple[str, str, float]:
        """Return (text, language code, audio seconds)."""
        ...


class Speaker(Protocol):
    def voices(self) -> list[str]: ...

    def speak(self, text: str, voice: str) -> tuple[bytes, float]:
        """Return (WAV bytes, audio seconds)."""
        ...


_MARKDOWN = re.compile(r"[`*_#>]+")
_SPACES = re.compile(r"\s+")


def speakable(text: str) -> str:
    """Plain text for the voice: no markdown marks, single spaces, bounded length."""
    plain = _SPACES.sub(" ", _MARKDOWN.sub("", text)).strip()
    if len(plain) <= MAX_SPEAK_CHARS:
        return plain
    cut = plain[:MAX_SPEAK_CHARS]
    end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    return cut[: end + 1] if end > MAX_SPEAK_CHARS // 2 else cut


class SpeechService:
    def __init__(self, transcriber: Transcriber, speaker: Speaker) -> None:
        self._transcriber = transcriber
        self._speaker = speaker
        self._listen_lock = asyncio.Lock()
        self._speak_lock = asyncio.Lock()
        self.transcriptions = 0
        self.spoken = 0
        self.last_transcribe_seconds: float | None = None
        self.last_speak_seconds: float | None = None

    async def transcribe(self, audio: bytes) -> Transcript:
        if not audio:
            raise SpeechError("the recording is empty")
        if len(audio) > MAX_AUDIO_BYTES:
            raise SpeechError("the recording is too long")
        async with self._listen_lock:
            started = time.perf_counter()
            text, language, audio_seconds = await asyncio.to_thread(self._transcriber.transcribe, audio)
            seconds = time.perf_counter() - started
        self.transcriptions += 1
        self.last_transcribe_seconds = round(seconds, 3)
        return Transcript(text.strip(), language, round(audio_seconds, 2), round(seconds, 3))

    async def speak(self, text: str, voice: str | None = None) -> Speech:
        plain = speakable(text)
        if not plain:
            raise SpeechError("there is nothing to say")
        chosen = voice or DEFAULT_VOICE
        if chosen not in await self.voices():
            raise SpeechError(f"unknown voice {chosen!r}")
        async with self._speak_lock:
            started = time.perf_counter()
            wav, audio_seconds = await asyncio.to_thread(self._speaker.speak, plain, chosen)
            seconds = time.perf_counter() - started
        self.spoken += 1
        self.last_speak_seconds = round(seconds, 3)
        return Speech(wav, round(audio_seconds, 2), round(seconds, 3), chosen)

    async def voices(self) -> list[str]:
        """The voice names. Loading the voice model the first time can take a while, so it runs in a thread."""
        return sorted(await asyncio.to_thread(self._speaker.voices))
