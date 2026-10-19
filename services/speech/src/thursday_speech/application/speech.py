"""Speech use cases: turn a recorded clip into text, and turn a reply into audio.

The engines are behind small interfaces so the service can be tested without models, and so a
different engine can replace one later. Both engines are loaded on first use, run in a worker
thread (they are CPU-bound), and take one request at a time each. An engine nobody has used for a
while is dropped from memory and loads again on the next use.
"""

import asyncio
import contextlib
import re
import time
from collections.abc import Callable
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


Decoder = Callable[[bytes], tuple[bytes, float]]
"""A recording in any format to (WAV bytes, seconds)."""


class SpeechService:
    def __init__(self, transcriber: Transcriber, speaker: Speaker, decoder: Decoder | None = None) -> None:
        self._transcriber = transcriber
        self._speaker = speaker
        self._decoder = decoder
        self._last_listen = self._last_speak = time.monotonic()
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
            self._last_listen = time.monotonic()
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
            self._last_speak = time.monotonic()
        self.spoken += 1
        self.last_speak_seconds = round(seconds, 3)
        return Speech(wav, round(audio_seconds, 2), round(seconds, 3), chosen)

    async def to_wav(self, audio: bytes) -> tuple[bytes, float]:
        """The recording as plain WAV, for a model that hears. Needs no speech engine."""
        if self._decoder is None:
            raise EngineUnavailable("this service cannot decode recordings")
        if not audio:
            raise SpeechError("the recording is empty")
        if len(audio) > MAX_AUDIO_BYTES:
            raise SpeechError("the recording is too long")
        return await asyncio.to_thread(self._decoder, audio)

    async def warm(self, *, listen: bool, speak: bool) -> list[str]:
        """Load the engines a spoken turn is about to need. Returns the names loaded now; an engine that is
        loaded already, or cannot be warmed, is left as it is. Counts as a use, so it is not dropped again
        before the turn arrives."""
        loaded: list[str] = []
        for wanted, name, engine, lock in (
            (listen, "speech to text", self._transcriber, self._listen_lock),
            (speak, "text to speech", self._speaker, self._speak_lock),
        ):
            warm = getattr(engine, "warm", None)
            if not wanted or warm is None or getattr(engine, "loaded", False):
                continue
            async with lock:
                await asyncio.to_thread(warm)
            loaded.append(name)
        now = time.monotonic()
        if listen:
            self._last_listen = now
        if speak:
            self._last_speak = now
        return loaded

    async def unload_idle(self, minutes: float) -> list[str]:
        """Drop each engine that is loaded and has not been used for `minutes`. Returns the names dropped."""
        dropped: list[str] = []
        if not minutes:
            return dropped
        now = time.monotonic()
        for name, engine, lock, last in (
            ("speech to text", self._transcriber, self._listen_lock, self._last_listen),
            ("text to speech", self._speaker, self._speak_lock, self._last_speak),
        ):
            unload = getattr(engine, "unload", None)
            if unload is None or not getattr(engine, "loaded", False) or lock.locked() or now - last < minutes * 60:
                continue
            async with lock:
                await asyncio.to_thread(unload)
            dropped.append(name)
        return dropped

    async def idle_loop(self, stop: asyncio.Event, minutes: float, every: float = 30.0) -> None:
        while not stop.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=every)
            await self.unload_idle(minutes)

    async def voices(self) -> list[str]:
        """The voice names. Loading the voice model the first time can take a while, so it runs in a thread."""
        return sorted(await asyncio.to_thread(self._speaker.voices))
