"""Delete saga: mark deleting, ask each owning service to delete (repeatable), then purge here.

Retries until every service confirms, so a service that is down only delays the delete.
"""

import asyncio
import contextlib
import logging

from thursday_gateway.application.waiting import wait_any
from thursday_gateway.domain.model import RecordState
from thursday_gateway.infrastructure.agents import AgentRefused, AgentUnavailable, MainAgentClient, VoiceAgentClient
from thursday_gateway.infrastructure.store import Store

log = logging.getLogger(__name__)


class DeletionSaga:
    """Deleting removes every trace of a chat or project from every service's data.

    The folder on disk is never touched.
    """

    def __init__(self, store: Store, main: MainAgentClient, voice: VoiceAgentClient) -> None:
        self._store = store
        self._main = main
        self._voice = voice
        self.wakeup = asyncio.Event()

    async def step(self) -> int:
        """One pass over everything marked deleting. Returns how many items are still pending."""
        pending = 0
        for chat in self._store.chats_in_state(RecordState.DELETING):
            try:
                for task_id in self._store.open_task_ids(chat.chat_id):
                    with contextlib.suppress(AgentRefused):  # already finished: nothing to stop
                        await self._main.cancel(task_id)
                response = await self._main.management("DELETE", f"/chats/{chat.chat_id}")
                if response.status_code >= 400:
                    raise AgentRefused(response.status_code, "main agent refused the delete")
                await self._voice.delete_chat(chat.chat_id)
            except (AgentUnavailable, AgentRefused) as exc:
                log.info("chat %s delete waiting: %s", chat.chat_id, exc)
                pending += 1
                continue
            self._store.purge_chat(chat.chat_id)
        for project in self._store.projects_in_state(RecordState.DELETING):
            if self._store.query("select 1 from chats where project_id = ?", (project.project_id,)):
                pending += 1
                continue
            try:
                response = await self._main.management("DELETE", f"/projects/{project.project_id}")
                if response.status_code >= 400:
                    raise AgentRefused(response.status_code, "main agent refused the delete")
            except (AgentUnavailable, AgentRefused) as exc:
                log.info("project %s delete waiting: %s", project.project_id, exc)
                pending += 1
                continue
            self._store.purge_project(project.project_id)
        return pending

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                pending = await self.step()
            except Exception:
                log.exception("delete saga step failed")
                pending = 1
            self.wakeup.clear()
            await wait_any(stop, self.wakeup, timeout=10 if pending else 60)
