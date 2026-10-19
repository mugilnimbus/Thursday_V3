"""What the voice agent needs to know about a recording before the model hears it."""

import io
import wave

MAX_HEAR_SECONDS = 30.0  # the documented limit of the models that take audio; a longer clip goes to speech-to-text


def wav_seconds(data: bytes) -> float | None:
    """How long a WAV clip is, or None when the bytes are not a readable WAV."""
    try:
        with wave.open(io.BytesIO(data), "rb") as clip:
            rate = clip.getframerate()
            return clip.getnframes() / rate if rate else None
    except (wave.Error, EOFError):
        return None


WORDS_PER_SECOND = 6.0  # faster than anyone speaks; a transcript beyond this was made up, not heard
FEWEST_WORDS_ALLOWED = 4


def plausible(text: str, seconds: float) -> bool:
    """False when the text has more words than could have been spoken in a clip of this length."""
    return len(text.split()) <= max(FEWEST_WORDS_ALLOWED, seconds * WORDS_PER_SECOND)
