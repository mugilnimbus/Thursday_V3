"""Dependency banners: voice agent, main agent, LLM endpoint, event ingest from each agent."""

import asyncio
import contextlib
from typing import Any

from thursday_gateway.application.hub import Hub
from thursday_gateway.application.relay import MessageRelay
from thursday_gateway.infrastructure.agents import MainAgentClient, VoiceAgentClient
from thursday_gateway.infrastructure.store import Store


class DependencyStatus:
    def __init__(
        self, store: Store, main: MainAgentClient, voice: VoiceAgentClient, relay: MessageRelay, hub: Hub
    ) -> None:
        self._store = store
        self._main = main
        self._voice = voice
        self._relay = relay
        self._hub = hub
        self.current: dict[str, Any] = {}

    async def check(self) -> dict[str, Any]:
        main_ready, voice_ready = await asyncio.gather(self._main.ready(), self._voice.ready())
        llm_ok = bool(main_ready and main_ready.get("checks", {}).get("llm_endpoint", {}).get("ok"))
        queued = len(self._store.query("select 1 from outgoing where status = 'queued'"))
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
