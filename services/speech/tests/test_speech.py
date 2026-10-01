from fastapi.testclient import TestClient
from pydantic import SecretStr
from thursday_speech.application.speech import MAX_SPEAK_CHARS, EngineUnavailable, speakable
from thursday_speech.bootstrap.main import SpeechSettings, create_app

TOKEN = "svc"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class FakeTranscriber:
    def __init__(self) -> None:
        self.broken = False

    def transcribe(self, audio: bytes) -> tuple[str, str, float]:
        if self.broken:
            raise EngineUnavailable("could not read the recording (InvalidDataError)")
        return f" heard {len(audio)} bytes ", "en", 1.5


class FakeSpeaker:
    def __init__(self) -> None:
        self.said: list[tuple[str, str]] = []

    def voices(self) -> list[str]:
        return ["af_heart", "am_adam"]

    def speak(self, text: str, voice: str) -> tuple[bytes, float]:
        self.said.append((text, voice))
        return b"RIFFfake", 2.0


def client(transcriber: FakeTranscriber | None = None, speaker: FakeSpeaker | None = None) -> TestClient:
    settings = SpeechSettings(_env_file=None, thursday_service_token=SecretStr(TOKEN))  # pyright: ignore[reportCallIssue]
    return TestClient(create_app(settings, transcriber or FakeTranscriber(), speaker or FakeSpeaker()))


def test_calls_need_the_service_token() -> None:
    c = client()
    assert c.post("/v1/transcribe", content=b"x").status_code == 401
    assert c.post("/v1/speak", json={"text": "hi"}).status_code == 401
    assert c.get("/health").status_code == 200


def test_transcribe_returns_trimmed_text_and_timing() -> None:
    body = client().post("/v1/transcribe", content=b"12345", headers=AUTH).json()
    assert body["text"] == "heard 5 bytes" and body["language"] == "en" and body["audio_seconds"] == 1.5


def test_transcribe_rejects_empty_and_reports_unreadable_audio() -> None:
    assert client().post("/v1/transcribe", content=b"", headers=AUTH).status_code == 422
    broken = FakeTranscriber()
    broken.broken = True
    response = client(broken).post("/v1/transcribe", content=b"junk", headers=AUTH)
    assert response.status_code == 503 and "recording" in response.json()["detail"]


def test_speak_returns_wav_and_cleans_markdown() -> None:
    speaker = FakeSpeaker()
    text = "Done. I deleted `old.log`.\n\n**Three** files left."
    response = client(speaker=speaker).post("/v1/speak", json={"text": text}, headers=AUTH)
    assert response.status_code == 200 and response.headers["content-type"] == "audio/wav"
    assert response.content == b"RIFFfake" and response.headers["x-voice"] == "af_heart"
    assert speaker.said == [("Done. I deleted old.log. Three files left.", "af_heart")]


def test_speak_rejects_unknown_voices_and_empty_text() -> None:
    c = client()
    assert c.post("/v1/speak", json={"text": "hi", "voice": "nope"}, headers=AUTH).status_code == 422
    assert c.post("/v1/speak", json={"text": "``` ```"}, headers=AUTH).status_code == 422
    assert c.get("/v1/voices", headers=AUTH).json() == {"voices": ["af_heart", "am_adam"]}


def test_long_replies_are_cut_at_a_sentence() -> None:
    cut = speakable("One sentence here. " * 400)
    assert len(cut) <= MAX_SPEAK_CHARS and cut.endswith(".")
