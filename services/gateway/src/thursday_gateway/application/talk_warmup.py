"""Getting ready for a turn before it needs anything.

Models that nobody used for a while are unloaded to free the hardware, so the first turn after a break would
wait for them. Pressing the microphone starts loading what a spoken turn will need while the person is still
talking: the voice agent's model, the speech-to-text engine unless that model hears for itself, and the voice
when replies are read aloud. A typed message that will be read aloud starts loading the voice alone, while the
model writes its reply. Nothing here is needed for the turn to work; it only makes it start sooner.
"""

import asyncio
import logging

from thursday_gateway.application.errors import AgentRefused, AgentUnavailable
from thursday_gateway.application.ports import SpeechService, VoiceAgent

log = logging.getLogger(__name__)


class TalkWarmup:
    def __init__(self, speech: SpeechService, voice: VoiceAgent | None) -> None:
        self._speech = speech
        self._voice = voice
        self._running: set[asyncio.Task[None]] = set()

    def start(self, speak: bool, listen: bool = True) -> None:
        """Begin in the background and return at once. A warm-up already under way is not started twice."""
        if self._running:
            return
        task = asyncio.get_running_loop().create_task(self.run(speak, listen))
        self._running.add(task)
        task.add_done_callback(self._running.discard)

    async def run(self, speak: bool, listen: bool = True) -> None:
        if not listen:  # a typed message: the turn loads the voice model itself, only the voice is worth a head start
            await self._warm_speech(listen=False, speak=speak)
            return
        hears, _ = await asyncio.gather(self._load_voice_model(), self._warm_speech(listen=False, speak=speak))
        if not hears:
            await self._warm_speech(listen=True, speak=False)

    async def _load_voice_model(self) -> bool:
        """Load the voice agent's model. True when that model takes speech itself, so no speech-to-text is needed."""
        if self._voice is None:
            return False
        try:
            reply = await self._voice.request("POST", "/model/load")
            return reply.status_code < 400 and bool(reply.json().get("hears_audio"))
        except (AgentUnavailable, AgentRefused, ValueError) as exc:
            log.info("could not load the voice model ahead of the turn: %s", exc)
            return False

    async def _warm_speech(self, *, listen: bool, speak: bool) -> None:
        if not (listen or speak):
            return
        try:
            await self._speech.call("POST", "/warm", json={"listen": listen, "speak": speak})
        except (AgentUnavailable, AgentRefused) as exc:
            log.info("could not warm the speech engines ahead of the turn: %s", exc)
