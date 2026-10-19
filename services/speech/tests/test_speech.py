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


def test_a_recording_is_decoded_to_wav_without_loading_a_speech_engine() -> None:
    import io
    import wave

    from thursday_speech.infrastructure.decode import to_wav

    source = io.BytesIO()
    with wave.open(source, "wb") as clip:
        clip.setnchannels(2)
        clip.setsampwidth(2)
        clip.setframerate(44100)
        clip.writeframes(b"\x01\x00\xff\xff" * 44100)  # one second of stereo
    settings = SpeechSettings(_env_file=None, thursday_service_token=SecretStr(TOKEN))  # pyright: ignore[reportCallIssue]
    transcriber, speaker = FakeTranscriber(), FakeSpeaker()
    with TestClient(create_app(settings, transcriber, speaker, to_wav)) as c:
        out = c.post("/v1/decode", content=source.getvalue(), headers=AUTH)
        assert out.status_code == 200 and out.headers["content-type"] == "audio/wav"
        with wave.open(io.BytesIO(out.content), "rb") as clip:
            assert (clip.getnchannels(), clip.getframerate(), clip.getsampwidth()) == (1, 16000, 2)
            assert abs(clip.getnframes() / 16000 - 1.0) < 0.05
        assert abs(float(out.headers["x-audio-seconds"]) - 1.0) < 0.05
        assert c.post("/v1/decode", content=b"not audio at all", headers=AUTH).status_code == 422
        assert c.post("/v1/decode", content=b"", headers=AUTH).status_code == 422
        assert c.post("/v1/decode", content=b"x").status_code == 401
    assert speaker.said == [], "decoding uses no speech engine"


async def test_a_speech_engine_nobody_used_for_a_while_is_dropped_and_one_in_use_is_kept() -> None:
    from thursday_speech.application.speech import SpeechService

    class Engine(FakeTranscriber):
        def __init__(self) -> None:
            super().__init__()
            self.loaded = False
            self.unloads = 0

        def transcribe(self, audio: bytes) -> tuple[str, str, float]:
            self.loaded = True
            return super().transcribe(audio)

        def unload(self) -> None:
            self.loaded = False
            self.unloads += 1

    engine = Engine()
    speech = SpeechService(engine, FakeSpeaker())
    assert await speech.unload_idle(5) == [], "nothing is loaded yet"
    await speech.transcribe(b"abc")
    assert await speech.unload_idle(5) == [] and engine.loaded, "just used"
    speech._last_listen -= 301
    assert await speech.unload_idle(0) == [] and engine.loaded, "0 keeps the engines loaded"
    assert await speech.unload_idle(5) == ["speech to text"] and not engine.loaded and engine.unloads == 1
    await speech.transcribe(b"abc")
    assert engine.loaded, "the next use loads it again"


async def test_warming_loads_only_the_engines_asked_for_and_counts_as_a_use() -> None:
    from thursday_speech.application.speech import SpeechService

    class Warmable:
        def __init__(self) -> None:
            self.loaded = False
            self.warmed = 0

        def warm(self) -> None:
            self.loaded = True
            self.warmed += 1

        def unload(self) -> None:
            self.loaded = False

    class Listener(Warmable, FakeTranscriber):
        def __init__(self) -> None:
            Warmable.__init__(self)
            FakeTranscriber.__init__(self)

    class Voice(Warmable, FakeSpeaker):
        def __init__(self) -> None:
            Warmable.__init__(self)
            FakeSpeaker.__init__(self)

    listener, voice = Listener(), Voice()
    speech = SpeechService(listener, voice)
    assert await speech.warm(listen=True, speak=False) == ["speech to text"] and not voice.loaded
    assert await speech.warm(listen=True, speak=True) == ["text to speech"], "what is loaded is not loaded again"
    assert (listener.warmed, voice.warmed) == (1, 1)
    speech._last_listen -= 301
    await speech.warm(listen=True, speak=False)
    assert await speech.unload_idle(5) == [], "a warm-up counts as a use: the engine stays for the turn"
    assert await SpeechService(FakeTranscriber(), FakeSpeaker()).warm(listen=True, speak=True) == [], "no warm-up to do"


def test_the_warm_route_answers_at_once() -> None:
    with client() as c:
        assert c.post("/v1/warm", json={"listen": True, "speak": True}).status_code == 401
        answer = c.post("/v1/warm", json={"listen": True, "speak": True}, headers=AUTH)
        assert answer.status_code == 202 and answer.json() == {"warming": True}
