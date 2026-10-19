"""One conversational turn: a plain streaming loop with the voice LLM and its task tools.

Approval answers never go through the model: when an approval is pending in the chat and
the whole message is a recognised approval phrase, code answers it directly.
"""

import json
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, cast

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    messages_from_dict,
    messages_to_dict,
)
from thursday_contracts.events import EventType
from thursday_llm.runtime import LlmRuntime

from thursday_voice_agent.application.errors import ChatDeleted
from thursday_voice_agent.application.history import fit_in_steps, trim_orphans, window_start
from thursday_voice_agent.application.model_stream import ModelStream, VoiceModelUnavailable
from thursday_voice_agent.application.ports import ConversationRecords, Events
from thursday_voice_agent.application.prompts import REPORT_RULE
from thursday_voice_agent.application.task_tools import TOOLS, run_tool
from thursday_voice_agent.application.tasks import TaskRelay
from thursday_voice_agent.domain.reports import finished_note, report_problem, started_note
from thursday_voice_agent.domain.spoken import spoken_approval
from thursday_voice_agent.domain.tasks import DelegatedTask, request_name

log = logging.getLogger(__name__)
MAX_TOOL_ROUNDS = 4
HISTORY_MESSAGES = 60
HISTORY_STEP = 20


@dataclass(frozen=True, slots=True)
class Project:
    project_id: str
    folder: str


def direct_call_id(task_id: str) -> str:
    return f"direct-{task_id}"


class Conversation:
    def __init__(
        self,
        store: ConversationRecords,
        relay: TaskRelay,
        llm: LlmRuntime,
        events: Events,
        system_prompt: Callable[[], str],
    ) -> None:
        self._store = store
        self._relay = relay
        self._llm = llm
        self._events = events
        self._system_prompt = system_prompt
        self._model = ModelStream(llm, events)

    @property
    def last_llm(self) -> dict[str, Any]:
        """Speed and context use of the last model call, for the service's metrics."""
        return self._model.last_llm

    def _history(self, chat_id: str) -> list[AnyMessage]:
        """The recent conversation the model sees: at most the last 60 messages, cut to the chosen token count if
        one is set. The window starts at the same message for many turns (see `history`), so the model server
        can reuse what it already worked out."""
        start = window_start(self._store.transcript_count(chat_id), HISTORY_MESSAGES, HISTORY_STEP)
        recent = cast(list[AnyMessage], messages_from_dict(self._store.transcript_from(chat_id, start)))
        return fit_in_steps(recent, self._llm.config.compact_at_tokens, HISTORY_STEP)

    async def turn(self, chat_id: str, client_message_id: str, text: str, project: Project) -> AsyncIterator[dict]:
        if self._store.chat_deleted(chat_id):
            raise ChatDeleted(chat_id)
        done = self._store.turn_reply(chat_id, client_message_id)
        if done is not None:
            yield {"type": "done", "text": done, "replayed": True}
            return
        pending = self._store.pending_approval(chat_id)
        decision = spoken_approval(text) if pending else None
        if decision is None and not await self._llm.provider.reachable():
            raise VoiceModelUnavailable("the voice model endpoint is unreachable")
        self._events.publish(
            EventType.USER_MESSAGE,
            {"text": text, "client_message_id": client_message_id},
            project_id=project.project_id,
            chat_id=chat_id,
        )
        if pending is not None and decision is not None:
            reply = await self._relay.answer_spoken(chat_id, pending, decision)
            yield {"type": "delta", "text": reply}
            self._finish(chat_id, client_message_id, project, [HumanMessage(text), AIMessage(reply)], reply)
            yield {"type": "done", "text": reply}
            return
        history = trim_orphans(self._history(chat_id))
        new: list[AnyMessage] = [HumanMessage(text)]
        reply = ""
        delegations = 0  # how many tasks this message has started so far: part of each request's name
        for _ in range(MAX_TOOL_ROUNDS):
            message = None
            view = [SystemMessage(self._system_prompt()), *history, *new]
            async for kind, value in self._model.reply(view, chat_id, project.project_id, TOOLS):
                if kind == "delta":
                    yield {"type": "delta", "text": value}
                else:
                    message = value
            assert isinstance(message, AIMessage)
            new.append(message)
            reply = message.text.strip() or reply
            if not message.tool_calls:
                break
            for call in message.tool_calls:
                request = None
                if call["name"] == "delegate_task":
                    request = request_name(chat_id, client_message_id, delegations)
                    delegations += 1
                result = await run_tool(
                    self._relay, call["name"], call["args"], chat_id, project.project_id, project.folder, request
                )
                new.append(ToolMessage(result, tool_call_id=call["id"] or call["name"]))
        reply = reply or "Okay."
        self._finish(chat_id, client_message_id, project, new, reply)
        yield {"type": "done", "text": reply}

    async def direct(self, chat_id: str, client_message_id: str, text: str, project: Project) -> dict[str, Any]:
        """Send the user's words to the main agent unchanged. No model runs here: the voice model is only asked
        later, by `report`, to put the result into words. The transcript is written as if the voice agent had
        delegated the task, so a later "what did we just do?" has something to go on."""
        if self._store.chat_deleted(chat_id):
            raise ChatDeleted(chat_id)
        if self._store.turn_reply(chat_id, client_message_id) is not None:
            return {"replayed": True}

        def publish_user_message() -> None:
            self._events.publish(
                EventType.USER_MESSAGE,
                {"text": text, "client_message_id": client_message_id, "direct": True},
                project_id=project.project_id,
                chat_id=chat_id,
            )

        pending = self._store.pending_approval(chat_id)
        decision = spoken_approval(text) if pending else None
        if pending is not None and decision is not None:  # a plain "yes" or "no" answers a waiting approval here too
            publish_user_message()
            reply = await self._relay.answer_spoken(chat_id, pending, decision)
            self._finish(chat_id, client_message_id, project, [HumanMessage(text), AIMessage(reply)], reply)
            return {"answered": reply}
        task = await self._relay.delegate(
            chat_id,
            project.project_id,
            project.folder,
            text,
            direct=True,
            before_announced=publish_user_message,
            request=request_name(chat_id, client_message_id),
        )
        call_id = direct_call_id(task.task_id)
        note = started_note(task.task_id[:8])
        started: list[AnyMessage] = [
            HumanMessage(text),
            AIMessage("", tool_calls=[{"name": "delegate_task", "args": {"instruction": text}, "id": call_id}]),
            ToolMessage(note, tool_call_id=call_id),
        ]
        self._store.append(chat_id, json.loads(json.dumps(messages_to_dict(started), default=str)))
        self._store.save_turn(chat_id, client_message_id, note)
        return {"task_id": task.task_id}

    async def report(self, task: DelegatedTask) -> str | None:
        """The voice model's one or two sentences about a finished direct task, or None when they cannot be trusted
        (model unreachable, empty, tool-call syntax, or a claim that work is still going on). The caller then shows
        the main agent's own words. The model is shown the task as if it had delegated it itself and is offered no
        tools, so it can only report."""
        if not await self._llm.provider.reachable():
            return None
        message = None
        async for kind, value in self._model.reply(self._report_view(task), task.chat_id, task.project_id, None):
            if kind == "message":
                message = value
        text = message.text.strip() if isinstance(message, AIMessage) else ""
        problem = report_problem(text)
        if problem is not None:
            log.warning("report on task %s rejected (%s)", task.task_id, problem)
            return None
        return text

    def _report_view(self, task: DelegatedTask) -> list[AnyMessage]:
        history = trim_orphans(self._history(task.chat_id))
        call_id = direct_call_id(task.task_id)
        at = next(
            (
                i
                for i, m in enumerate(history)
                if isinstance(m, AIMessage) and any(c["id"] == call_id for c in m.tool_calls)
            ),
            None,
        )
        earlier = history[: max(at - 1, 0)] if at is not None else history  # what was said before the user's message
        return [
            SystemMessage(self._system_prompt() + REPORT_RULE),
            *earlier,
            HumanMessage(task.instruction),
            AIMessage(
                "", tool_calls=[{"name": "delegate_task", "args": {"instruction": task.instruction}, "id": call_id}]
            ),
            ToolMessage(finished_note(task.task_id[:8], task.summary), tool_call_id=call_id),
        ]

    def _finish(
        self, chat_id: str, client_message_id: str, project: Project, new: list[AnyMessage], reply: str
    ) -> None:
        self._store.append(chat_id, json.loads(json.dumps(messages_to_dict(new), default=str)))
        self._store.save_turn(chat_id, client_message_id, reply)
        self._events.publish(
            EventType.ASSISTANT_MESSAGE,
            {"text": reply, "client_message_id": client_message_id},
            project_id=project.project_id,
            chat_id=chat_id,
        )
