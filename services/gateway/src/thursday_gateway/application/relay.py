"""Chat relay: user messages go to the voice agent in order; queued while it is down.

Replies stream back as ephemeral `chat_delta` messages; the stored chat history comes
from the voice agent's own `user_message` / `assistant_message` events.
"""

import asyncio
import contextlib
import logging

from thursday_gateway.application.hub import Hub
from thursday_gateway.application.projects import ProjectService
from thursday_gateway.application.waiting import wait_any
from thursday_gateway.domain.model import OutgoingStatus
from thursday_gateway.infrastructure.agents import AgentRefused, AgentUnavailable, VoiceAgentClient
from thursday_gateway.infrastructure.store import Store

log = logging.getLogger(__name__)


class MessageRelay:
    def __init__(self, store: Store, projects: ProjectService, voice: VoiceAgentClient, hub: Hub) -> None:
        self._store = store
        self._projects = projects
        self._voice = voice
        self._hub = hub
        self.wakeup = asyncio.Event()
        self.voice_reachable = True

    def accept(self, chat_id: str, client_message_id: str, text: str) -> tuple[OutgoingStatus, bool]:
        record, new = self._store.enqueue(chat_id, client_message_id, text)
        if new:
            self._hub.publish(
                {
                    "kind": "outgoing",
                    "chat_id": chat_id,
                    "client_message_id": client_message_id,
                    "status": record.status.value,
                    "text": text,
                }
            )
            self.wakeup.set()
        return record.status, new

    async def deliver_one(self) -> bool:
        """Deliver the oldest queued message. Returns False when nothing was delivered."""
        out = self._store.next_queued()
        if out is None:
            return False
        chat = self._store.chat(out.chat_id)
        project = self._store.project(chat.project_id) if chat else None
        if chat is None or project is None:
            self._store.set_outgoing(out.id, OutgoingStatus.FAILED, "chat no longer exists")
            return True
        body = {
            "client_message_id": out.client_message_id,
            "text": out.text,
            "project_id": project.project_id,
            "project_folder": project.folder,
        }
        try:
            async for part in self._voice.turn(out.chat_id, body):
                if part.get("type") == "delta":
                    self._hub.publish(
                        {
                            "kind": "chat_delta",
                            "chat_id": out.chat_id,
                            "client_message_id": out.client_message_id,
                            "text": part.get("text", ""),
                        }
                    )
                elif part.get("type") == "error":
                    raise AgentRefused(500, str(part.get("message", "voice agent error")))
        except AgentUnavailable as exc:
            self._store.set_outgoing(out.id, OutgoingStatus.QUEUED, str(exc), attempt=True)
            raise
        except AgentRefused as exc:
            self._store.set_outgoing(out.id, OutgoingStatus.FAILED, str(exc), attempt=True)
            self._hub.publish(
                {
                    "kind": "outgoing",
                    "chat_id": out.chat_id,
                    "client_message_id": out.client_message_id,
                    "status": "failed",
                    "error": str(exc),
                }
            )
            return True
        self._store.set_outgoing(out.id, OutgoingStatus.DELIVERED, attempt=True)
        self._hub.publish(
            {
                "kind": "outgoing",
                "chat_id": out.chat_id,
                "client_message_id": out.client_message_id,
                "status": "delivered",
            }
        )
        return True

    async def run(self, stop: asyncio.Event) -> None:
        delay = 1.0
        while not stop.is_set():
            try:
                delivered = await self.deliver_one()
                self.voice_reachable = True
                delay = 1.0
                if delivered:
                    continue
            except AgentUnavailable:
                if self.voice_reachable:
                    log.warning("voice agent unreachable; messages stay queued")
                self.voice_reachable = False
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=delay)
                delay = min(delay * 2, 30.0)
                continue
            except Exception:
                log.exception("message relay failed")
            self.wakeup.clear()
            await wait_any(stop, self.wakeup, timeout=5)
