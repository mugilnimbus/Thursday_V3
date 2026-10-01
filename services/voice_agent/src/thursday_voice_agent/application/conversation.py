"""One conversational turn: a plain streaming loop with the voice LLM and its task tools.

Approval answers never go through the model: when an approval is pending in the chat and
the whole message is a recognised approval phrase, code answers it directly.
"""

import json
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, cast

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    messages_from_dict,
    messages_to_dict,
)
from langchain_core.messages.utils import message_chunk_to_message
from thursday_contracts.events import EventType
from thursday_llm.chat import StreamTiming
from thursday_llm.runtime import LlmRuntime
from thursday_runtime.outbox import EventPublisher

from thursday_voice_agent.application.tasks import TaskRelay
from thursday_voice_agent.domain.spoken import spoken_approval
from thursday_voice_agent.infrastructure.main_agent import MainAgentRefused, MainAgentUnavailable
from thursday_voice_agent.infrastructure.store import Store

MAX_TOOL_ROUNDS = 4
HISTORY_MESSAGES = 60


def _fn(
    name: str,
    description: str,
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties or {}, "required": required or []},
        },
    }


TASK_ID = {"task_id": {"type": "string", "description": "Optional; defaults to the most recent running task."}}
TOOLS = [
    _fn(
        "delegate_task",
        "Hand work on the PC to the main agent.",
        {"instruction": {"type": "string", "description": "One clear, complete instruction."}},
        ["instruction"],
    ),
    _fn("list_tasks", "List this chat's tasks with their state and results."),
    _fn("pause_task", "Pause a running task after its current step.", TASK_ID),
    _fn("resume_task", "Resume a paused task.", TASK_ID),
    _fn("stop_task", "Stop a running task now.", TASK_ID),
]


class VoiceModelUnavailable(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Project:
    project_id: str
    folder: str


def text_of(chunk: AIMessageChunk) -> str:
    if isinstance(chunk.content, str):
        return chunk.content
    return "".join(b.get("text", "") for b in chunk.content if isinstance(b, dict) and b.get("type") == "text")


class Conversation:
    def __init__(
        self,
        store: Store,
        relay: TaskRelay,
        llm: LlmRuntime,
        events: EventPublisher,
        system_prompt: Callable[[], str],
    ) -> None:
        self._store = store
        self._relay = relay
        self._llm = llm
        self._events = events
        self._system_prompt = system_prompt
        self.last_llm: dict[str, Any] = {}

    async def turn(self, chat_id: str, client_message_id: str, text: str, project: Project) -> AsyncIterator[dict]:
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
        history = cast(list[AnyMessage], messages_from_dict(self._store.transcript(chat_id, HISTORY_MESSAGES)))
        new: list[AnyMessage] = [HumanMessage(text)]
        reply = ""
        for _ in range(MAX_TOOL_ROUNDS):
            message = None
            async for kind, value in self._stream(
                [SystemMessage(self._system_prompt()), *history, *new], chat_id, project
            ):
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
                result = await self._run_tool(call["name"], call["args"], chat_id, project)
                new.append(ToolMessage(result, tool_call_id=call["id"] or call["name"]))
        reply = reply or "Okay."
        self._finish(chat_id, client_message_id, project, new, reply)
        yield {"type": "done", "text": reply}

    async def _stream(
        self, messages: list[AnyMessage], chat_id: str, project: Project
    ) -> AsyncIterator[tuple[str, Any]]:
        loaded = await self._llm.provider.ensure_loaded()
        timing = StreamTiming()
        chunk: AIMessageChunk | None = None
        started = time.perf_counter()
        async for raw in self._llm.chat.bind_tools(TOOLS).astream(messages):
            part = cast(AIMessageChunk, raw)
            delta = text_of(part)
            # Any content counts, reasoning included: output_tokens includes reasoning, so starting the
            # clock at the first visible text would overstate the token rate (as the main agent does).
            if part.content or part.tool_call_chunks:
                timing.token_seen()
            if delta:
                yield "delta", delta
            chunk = part if chunk is None else chunk + part
        timing.finish()
        if chunk is None:
            raise VoiceModelUnavailable("the voice model returned nothing")
        message = message_chunk_to_message(chunk)
        usage = dict(getattr(message, "usage_metadata", None) or {})
        self._events.publish(
            EventType.LLM_CALL,
            {
                "agent": "voice",
                "status": "ok",
                "usage": usage,
                "ttft_seconds": timing.ttft_seconds,
                "tokens_per_second": timing.tokens_per_second(cast(int | None, usage.get("output_tokens"))),
                "context_length": loaded.context_length,
                "seconds": round(time.perf_counter() - started, 3),
                "text": getattr(message, "text", ""),
                "tool_calls": [c["name"] for c in getattr(message, "tool_calls", [])],
            },
            project_id=project.project_id,
            chat_id=chat_id,
        )
        self.last_llm = {
            "llm_ttft_seconds": timing.ttft_seconds,
            "context_length": loaded.context_length,
            "llm_tokens_per_second": timing.tokens_per_second(cast(int | None, usage.get("output_tokens"))),
            "llm_input_tokens": usage.get("input_tokens"),
        }
        yield "message", message

    async def _run_tool(self, name: str, args: dict[str, Any], chat_id: str, project: Project) -> str:
        try:
            if name == "delegate_task":
                instruction = str(args.get("instruction", "")).strip()
                if not instruction:
                    return "No instruction given."
                task = await self._relay.delegate(chat_id, project.project_id, project.folder, instruction)
                return f"Task {task.task_id[:8]} started."
            if name == "list_tasks":
                return self._relay.describe(chat_id)
            if name in ("pause_task", "resume_task", "stop_task"):
                return await self._relay.control(chat_id, name.removesuffix("_task"), args.get("task_id"))
        except MainAgentUnavailable:
            return "The main agent is not reachable right now."
        except MainAgentRefused as exc:
            return f"The main agent refused: {exc}"
        return f"Unknown tool {name}."

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
