"""Turn a recording in any common format (webm, m4a, wav, mp3) into plain WAV: 16 kHz, mono, 16-bit.

A model that hears takes WAV, while browsers record webm and phones m4a. Decoding needs no speech model.
"""

import io
import wave

from thursday_speech.application.speech import SpeechError

RATE = 16_000


def to_wav(audio: bytes) -> tuple[bytes, float]:
    """Return (WAV bytes, seconds of audio)."""
    import av

    pcm = bytearray()
    try:
        with av.open(io.BytesIO(audio), mode="r") as container:
            stream = next((s for s in container.streams if s.type == "audio"), None)
            if stream is None:
                raise SpeechError("the recording has no sound in it")
            resampler = av.AudioResampler(format="s16", layout="mono", rate=RATE)
            for frame in container.decode(stream):
                if not isinstance(frame, av.AudioFrame):
                    continue
                for out in resampler.resample(frame):
                    pcm += out.to_ndarray().tobytes()
            for out in resampler.resample(None):
                pcm += out.to_ndarray().tobytes()
    except SpeechError:
        raise
    except Exception as exc:  # PyAV raises many kinds of error for a damaged or unknown file
        raise SpeechError(f"could not read the recording ({type(exc).__name__})") from exc
    if not pcm:
        raise SpeechError("the recording is empty")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(bytes(pcm))
    return buffer.getvalue(), len(pcm) / 2 / RATE
