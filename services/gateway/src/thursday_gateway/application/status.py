"""Dependency banners: voice agent, main agent, LLM endpoint, event ingest from each agent.

An agent is asked every few seconds whether it is ready, with a short wait. One missed answer is not an agent
that stopped: a busy moment can outlast the wait. So an agent counts as down from the second miss in a row, and
until then its last answer stands. A real outage is therefore shown one check later than it could be.
"""

import asyncio
import contextlib
from typing import Any

from thursday_gateway.application.hub import Hub
from thursday_gateway.application.ports import MainAgent, StatusRecords, VoiceAgent
from thursday_gateway.application.relay import MessageRelay

MISSES_BEFORE_DOWN = 2


class DependencyStatus:
    def __init__(self, store: StatusRecords, main: MainAgent, voice: VoiceAgent, relay: MessageRelay, hub: Hub) -> None:
        self._store = store
        self._main = main
        self._voice = voice
        self._relay = relay
        self._hub = hub
        self.current: dict[str, Any] = {}
        self._missed = {"main": 0, "voice": 0}
        self._answered: dict[str, dict[str, Any] | None] = {"main": None, "voice": None}

    def _steady(self, agent: str, ready: dict[str, Any] | None) -> dict[str, Any] | None:
        """The answer to act on: the agent's own, or its last one while it has missed fewer checks than count."""
        if ready is not None:
            self._missed[agent] = 0
            self._answered[agent] = ready
            return ready
        self._missed[agent] += 1
        if self._missed[agent] >= MISSES_BEFORE_DOWN:
            self._answered[agent] = None
        return self._answered[agent]

    async def check(self) -> dict[str, Any]:
        answers = await asyncio.gather(self._main.ready(), self._voice.ready())
        main_ready, voice_ready = self._steady("main", answers[0]), self._steady("voice", answers[1])
        llm_ok = bool(main_ready and main_ready.get("checks", {}).get("llm_endpoint", {}).get("ok"))
        queued = self._store.queued_count()
        banners = []
        if main_ready is None:
            banners.append({"code": "main_agent_down", "text": "The main agent is not running. Tasks cannot start."})
        elif not llm_ok:
            banners.append({"code": "llm_endpoint_down", "text": "The LLM endpoint is unreachable. Tasks will retry."})
        if voice_ready is None:
            banners.append(
                {
                    "code": "voice_agent_down",
                    "text": "The voice agent is not running. Messages are queued."
                    if queued
                    else "The voice agent is not running.",
                }
            )
        return {
            "main_agent": main_ready is not None,
            "voice_agent": voice_ready is not None,
            "llm_endpoint": llm_ok,
            "queued_messages": queued,
            "banners": banners,
            "event_sources": self._store.last_seq(),
        }

    async def run(self, stop: asyncio.Event, interval: float = 5.0) -> None:
        while not stop.is_set():
            status = await self.check()
            if status["banners"] != self.current.get("banners"):
                self._hub.publish({"kind": "status_banner", "banners": status["banners"]})
            self.current = status
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=interval)
