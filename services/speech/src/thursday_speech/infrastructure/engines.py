"""The real engines: faster-whisper for speech to text and Kokoro (ONNX) for text to speech.

Both run on the CPU, because the GPUs are kept for the language models. Models load on first use:
Whisper downloads itself into the Hugging Face cache; the Kokoro model files are fetched once from
the kokoro-onnx project's release page into this service's data folder.
"""

import io
import logging
import threading
import wave
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from thursday_speech.application.speech import EngineUnavailable

log = logging.getLogger(__name__)

KOKORO_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
KOKORO_FILES = {"kokoro-v1.0.onnx": 300_000_000, "voices-v1.0.bin": 20_000_000}  # name: smallest plausible size


class WhisperTranscriber:
    def __init__(self, model_size: str) -> None:
        self._size = model_size
        self._model: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                try:
                    from faster_whisper import WhisperModel

                    self._model = WhisperModel(self._size, device="cpu", compute_type="int8")
                except Exception as exc:
                    raise EngineUnavailable(f"could not load the Whisper model ({type(exc).__name__})") from exc
                log.info("whisper model %s loaded", self._size)
            return self._model

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def transcribe(self, audio: bytes) -> tuple[str, str, float]:
        model = self._load()
        try:
            segments, info = model.transcribe(io.BytesIO(audio), beam_size=1, vad_filter=True)
            text = " ".join(segment.text.strip() for segment in segments)
        except Exception as exc:
            raise EngineUnavailable(f"could not read the recording ({type(exc).__name__})") from exc
        return text, str(info.language), float(info.duration)


class KokoroSpeaker:
    def __init__(self, model_dir: Path) -> None:
        self._dir = model_dir
        self._engine: Any = None
        self._voices: list[str] = []
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._engine is not None

    def files_present(self) -> bool:
        return all(
            (self._dir / name).is_file() and (self._dir / name).stat().st_size >= size
            for name, size in KOKORO_FILES.items()
        )

    def _download(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        for name, smallest in KOKORO_FILES.items():
            target = self._dir / name
            if target.is_file() and target.stat().st_size >= smallest:
                continue
            log.info("downloading %s", name)
            partial = target.with_suffix(target.suffix + ".part")
            with httpx.stream("GET", f"{KOKORO_RELEASE}/{name}", follow_redirects=True, timeout=600) as response:
                response.raise_for_status()
                with partial.open("wb") as out:
                    for chunk in response.iter_bytes(1 << 20):
                        out.write(chunk)
            if partial.stat().st_size < smallest:
                partial.unlink(missing_ok=True)
                raise OSError(f"{name} download was incomplete")
            partial.replace(target)

    def _load(self) -> Any:
        with self._lock:
            if self._engine is None:
                try:
                    self._download()
                    from kokoro_onnx import Kokoro

                    self._engine = Kokoro(str(self._dir / "kokoro-v1.0.onnx"), str(self._dir / "voices-v1.0.bin"))
                    self._voices = sorted(self._engine.get_voices())
                except Exception as exc:
                    raise EngineUnavailable(f"could not load the Kokoro voice model ({type(exc).__name__})") from exc
                log.info("kokoro loaded with %d voices", len(self._voices))
            return self._engine

    def voices(self) -> list[str]:
        self._load()
        return self._voices

    def speak(self, text: str, voice: str) -> tuple[bytes, float]:
        engine = self._load()
        try:
            samples, rate = engine.create(text, voice=voice, speed=1.0, lang="en-us")
        except Exception as exc:
            raise EngineUnavailable(f"could not make the audio ({type(exc).__name__})") from exc
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(rate)
            out.writeframes(pcm.tobytes())
        return buffer.getvalue(), len(pcm) / rate
