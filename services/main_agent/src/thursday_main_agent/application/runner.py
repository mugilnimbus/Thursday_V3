"""The agent loop: a LangGraph graph with an LLM step and a tools step, one thread per task.

- Pause lands at the start of the LLM step (a step is one LLM call plus its tool calls).
- Every tool call gets a mark keyed by our own ids. A finished call is never re-run when a
  node re-executes; a started call without a result reports "outcome unknown".
- When the tool server asks for input, an allow-always rule answers it, otherwise an
  approval opens and the graph interrupts. On resume the call is re-issued (the sealed
  requestState does not survive restarts) and answered from the stored decision.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, NotRequired, TypedDict, cast

import httpx
import openai
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    messages_from_dict,
)
from langchain_core.messages.utils import message_chunk_to_message
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, interrupt
from mcp_types import CallToolResult, ElicitResult, InputRequiredResult
from thursday_contracts.approvals import ApprovalRequest
from thursday_contracts.events import EventType
from thursday_llm.capture import CapturedExchange
from thursday_llm.chat import StreamTiming
from thursday_llm.providers import ProviderError
from thursday_llm.runtime import LlmRuntime

from thursday_main_agent.application.compaction import Compactor, estimate_tokens, summary_message
from thursday_main_agent.application.ports import Events, ToolServers
from thursday_main_agent.domain.approvals import Approval, ApprovalStatus
from thursday_main_agent.domain.tasks import TaskRecord
from thursday_main_agent.domain.tool_calls import UNKNOWN_OUTCOME, CallMark, MarkState, ToolNameMap, call_key
from thursday_main_agent.infrastructure.store import Store

log = logging.getLogger(__name__)
RETRYABLE = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.InternalServerError,
    openai.RateLimitError,
    httpx.HTTPError,
    ProviderError,
)
TOOL_SCHEMA_TOKENS = 1500  # rough allowance for tool definitions sent with every call
_CAPTURED: ContextVar[list[CapturedExchange] | None] = ContextVar("thursday_captured", default=None)


def capture_sink(exchange: CapturedExchange) -> None:
    captured = _CAPTURED.get()
    if captured is not None:
        captured.append(exchange)


class LlmUnavailable(Exception):
    pass


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    summary: NotRequired[str]
    summary_upto: NotRequired[int]


@dataclass(frozen=True, slots=True)
class RunnerSettings:
    approval_timeout: timedelta
    llm_retries: int
    retry_base_delay: float = 2.0
    compaction_threshold_percent: float = 90.0


@dataclass(slots=True)
class RunOutcome:
    kind: Literal["completed", "needs_approval", "paused", "failed"]
    text: str = ""
    approval: Approval | None = None


@dataclass(slots=True)
class _RunContext:
    task: TaskRecord
    names: ToolNameMap
    llm_tools: list[dict[str, Any]] = field(default_factory=list)


def tool_text(result: CallToolResult) -> str:
    parts = [getattr(c, "text", None) or f"[{c.type} content]" for c in result.content]
    return "\n".join(parts) or "(no output)"


class TaskRunner:
    def __init__(
        self,
        store: Store,
        events: Events,
        tools: ToolServers,
        llm: LlmRuntime,
        checkpointer: BaseCheckpointSaver,
        settings: RunnerSettings,
        system_prompt: Callable[[], str],
    ) -> None:
        self._store = store
        self._events = events
        self._tools = tools
        self._llm = llm
        self._settings = settings
        self._system_prompt = system_prompt
        self._contexts: dict[str, _RunContext] = {}
        self._checkpointer = checkpointer
        self.context_length: int | None = None
        self.last_llm: dict[str, Any] = {}
        self._compactor = Compactor(self._summarise, settings.compaction_threshold_percent)
        self._graph = self._build(checkpointer)

    # --- public --------------------------------------------------------------------------
    async def run(
        self, task: TaskRecord, *, instruction: str | None = None, resume: object | None = None
    ) -> RunOutcome:
        """Start (instruction), resume after an interrupt (resume), or continue after a restart (neither)."""
        mcp_tools = await self._tools.list_tools(task.project_id, task.project_folder)
        names = ToolNameMap([t.name for t in mcp_tools])
        llm_tools = [
            {
                "type": "function",
                "function": {
                    "name": names.to_llm(t.name),
                    "description": t.description or "",
                    "parameters": t.input_schema,
                },
            }
            for t in mcp_tools
        ]
        self._contexts[task.task_id] = _RunContext(task, names, llm_tools)
        config: RunnableConfig = {"configurable": {"thread_id": task.task_id}, "recursion_limit": 200}
        if instruction is not None:
            history = self.history_for(task.chat_id)
            task.history_len = len(history)
            self._store.save_task(task)
            graph_input: Any = {"messages": [*history, HumanMessage(instruction)]}
            saved = self._store.chat_summary(task.chat_id)
            if saved is not None and saved[0] <= len(history):
                graph_input.update(summary=saved[1], summary_upto=saved[0])
        elif resume is not None:
            graph_input = Command(resume=resume)
        else:
            graph_input = None
        try:
            async for _ in self._graph.astream(graph_input, config, stream_mode="updates", durability="sync"):
                pass
        except LlmUnavailable as exc:
            return RunOutcome("failed", str(exc))
        finally:
            self._contexts.pop(task.task_id, None)
        snapshot = await self._graph.aget_state(config)
        if snapshot.interrupts:
            value = snapshot.interrupts[0].value
            if value.get("kind") == "approval":
                return RunOutcome("needs_approval", approval=self._store.get_approval(value["approval_id"]))
            return RunOutcome("paused")
        messages = snapshot.values.get("messages", [])
        final = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        return RunOutcome("completed", final.text if final else "")

    @property
    def compaction_threshold_percent(self) -> float:
        return self._compactor.threshold_percent

    @compaction_threshold_percent.setter
    def compaction_threshold_percent(self, value: float) -> None:
        self._compactor.threshold_percent = value

    async def has_checkpoint(self, task_id: str) -> bool:
        snapshot = await self._graph.aget_state({"configurable": {"thread_id": task_id}})
        return bool(snapshot.values)

    async def forget(self, task_id: str) -> None:
        await self._checkpointer.adelete_thread(task_id)

    async def task_messages(self, task: TaskRecord) -> list[AnyMessage]:
        """This task's own messages (after the seeded chat history), with dangling tool calls closed."""
        snapshot = await self._graph.aget_state({"configurable": {"thread_id": task.task_id}})
        own = list(snapshot.values.get("messages", []))[task.history_len :] if snapshot.values else []
        return close_dangling_tool_calls(cast(list[AnyMessage], own))

    def history_for(self, chat_id: str) -> list[AnyMessage]:
        return cast(list[AnyMessage], list(messages_from_dict(self._store.load_transcript(chat_id))))

    # --- graph ---------------------------------------------------------------------------
    def _build(self, checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
        graph = StateGraph(State)
        graph.add_node("llm", self._llm_node)
        graph.add_node("tools", self._tools_node)
        graph.add_edge(START, "llm")
        graph.add_conditional_edges(
            "llm", lambda s: "tools" if getattr(s["messages"][-1], "tool_calls", None) else END, ["tools", END]
        )
        graph.add_edge("tools", "llm")
        return graph.compile(checkpointer=checkpointer)

    def _ctx(self, config: RunnableConfig) -> _RunContext:
        return self._contexts[config["configurable"]["thread_id"]]  # pyright: ignore[reportTypedDictNotRequiredAccess]

    async def _llm_node(self, state: State, config: RunnableConfig) -> dict[str, Any]:
        ctx = self._ctx(config)
        task = self._store.get_task(ctx.task.task_id) or ctx.task
        if task.reach_step_boundary():
            self._store.save_task(task)
            self._events.publish(
                EventType.TASK_STATE,
                {"state": "working", "pause_state": "paused"},
                project_id=task.project_id,
                chat_id=task.chat_id,
                task_id=task.task_id,
            )
            interrupt({"kind": "paused"})
        step = sum(1 for m in state["messages"][task.history_len :] if isinstance(m, AIMessage)) + 1
        updates = await self._compact_if_needed(task, state, step)
        summary = updates.get("summary", state.get("summary", ""))
        upto = updates.get("summary_upto", state.get("summary_upto", 0))
        message = await self._call_llm(
            task, self._view(summary, upto, state["messages"], task.history_len), ctx.llm_tools, step
        )
        return {"messages": [message], **updates}

    def _view(self, summary: str, upto: int, messages: list[AnyMessage], history_len: int) -> list[AnyMessage]:
        """What the model sees: system prompt, summary, the current instruction (always verbatim), recent messages."""
        head: list[AnyMessage] = [SystemMessage(self._system_prompt())]
        if summary:
            head.append(summary_message(summary))
        if upto > history_len < len(messages):
            head.append(messages[history_len])
        return [*head, *messages[upto:]]

    async def _compact_if_needed(self, task: TaskRecord, state: State, step: int) -> dict[str, Any]:
        try:
            self.context_length = (await self._llm.provider.ensure_loaded()).context_length or self.context_length
        except RETRYABLE:
            return {}
        summary, upto = state.get("summary", ""), state.get("summary_upto", 0)
        view_tokens = (
            estimate_tokens(self._view(summary, upto, state["messages"], task.history_len)) + TOOL_SCHEMA_TOKENS
        )
        if self.context_length is None or not self._compactor.needed(view_tokens, self.context_length):
            return {}
        result = await self._compactor.compact(state["messages"], summary, upto, self.context_length)
        if result is None:
            log.warning("context is %d tokens but nothing more can be summarised", view_tokens)
            return {}
        after = (
            estimate_tokens(self._view(result.summary, result.upto, state["messages"], task.history_len))
            + TOOL_SCHEMA_TOKENS
        )
        if after >= view_tokens:
            return {}  # nothing worth summarising yet (for example only the current instruction)
        if result.upto <= task.history_len:
            self._store.save_chat_summary(task.chat_id, result.upto, result.summary)
        self._events.publish(
            EventType.COMPACTION,
            {
                "step": step,
                "estimated_tokens_before": view_tokens,
                "estimated_tokens_after": after,
                "context_length": self.context_length,
                "summarised_messages": result.summarised_messages,
                "summary": result.summary,
            },
            project_id=task.project_id,
            chat_id=task.chat_id,
            task_id=task.task_id,
        )
        return {"summary": result.summary, "summary_upto": result.upto}

    async def _summarise(self, messages: list[AnyMessage]) -> str:
        chunk: AIMessageChunk | None = None
        async for raw in self._llm.chat.astream(messages):
            part = cast(AIMessageChunk, raw)
            chunk = part if chunk is None else chunk + part  # pyright: ignore[reportOperatorIssue]
        return chunk.text if chunk is not None else ""

    async def _call_llm(
        self, task: TaskRecord, messages: list[AnyMessage], tools: list[dict[str, Any]], step: int
    ) -> AIMessage:
        attempts = self._settings.llm_retries + 1
        for attempt in range(1, attempts + 1):
            captured: list[CapturedExchange] = []
            token = _CAPTURED.set(captured)
            timing = StreamTiming()
            try:
                loaded = await self._llm.provider.ensure_loaded()
                self.context_length = loaded.context_length
                if not loaded.adopted:
                    self._events.publish(
                        EventType.MODEL_LOAD,
                        {
                            "model": loaded.key,
                            "context_length": loaded.context_length,
                            "load_seconds": loaded.load_seconds,
                        },
                    )
                timing = StreamTiming()
                chunk: AIMessageChunk | None = None
                async for raw in self._llm.chat.bind_tools(tools).astream(messages):
                    part = cast(AIMessageChunk, raw)
                    if part.content or part.tool_call_chunks:
                        timing.token_seen()
                    chunk = part if chunk is None else chunk + part  # pyright: ignore[reportOperatorIssue]
                timing.finish()
                if chunk is None:
                    raise LlmUnavailable("the model returned nothing")
                message = message_chunk_to_message(chunk)
                assert isinstance(message, AIMessage)
                self._publish_llm_call(task, step, attempt, "ok", message, timing, captured)
                return message
            except RETRYABLE as exc:
                self._publish_llm_call(task, step, attempt, f"error: {type(exc).__name__}", None, timing, captured)
                if attempt == attempts:
                    raise LlmUnavailable(f"the model endpoint failed {attempts} times ({type(exc).__name__})") from exc
                await asyncio.sleep(self._settings.retry_base_delay * 2 ** (attempt - 1))
            except openai.APIStatusError as exc:
                self._publish_llm_call(task, step, attempt, f"error: {exc.status_code}", None, timing, captured)
                raise LlmUnavailable(f"the model endpoint refused the request ({exc.status_code})") from exc
            finally:
                _CAPTURED.reset(token)
        raise LlmUnavailable("unreachable")

    def _publish_llm_call(
        self,
        task: TaskRecord,
        step: int,
        attempt: int,
        status: str,
        message: AIMessage | None,
        timing: StreamTiming,
        captured: list[CapturedExchange],
    ) -> None:
        usage = dict(message.usage_metadata or {}) if message is not None else {}
        exchange = captured[-1] if captured else None
        tps = timing.tokens_per_second(cast(int | None, usage.get("output_tokens")))
        if message is not None:
            self.last_llm = {
                "llm_ttft_seconds": timing.ttft_seconds,
                "llm_tokens_per_second": tps,
                "llm_input_tokens": usage.get("input_tokens"),
                "context_length": self.context_length,
            }
        self._events.publish(
            EventType.LLM_CALL,
            {
                "agent": "main",
                "step": step,
                "attempt": attempt,
                "status": status,
                "usage": usage,
                "ttft_seconds": timing.ttft_seconds,
                "tokens_per_second": tps,
                "context_length": self.context_length,
                "tool_calls": [c["name"] for c in message.tool_calls] if message is not None else [],
                "text": message.text if message is not None else "",
                "request_body": exchange.request_body if exchange else None,
                "response_body": exchange.response_text if exchange else None,
                "body_truncated": exchange.truncated if exchange else False,
            },
            project_id=task.project_id,
            chat_id=task.chat_id,
            task_id=task.task_id,
        )

    async def _tools_node(self, state: State, config: RunnableConfig) -> dict[str, Any]:
        ctx = self._ctx(config)
        task = self._store.get_task(ctx.task.task_id) or ctx.task
        ai = state["messages"][-1]
        assert isinstance(ai, AIMessage)
        step = sum(1 for m in state["messages"][task.history_len :] if isinstance(m, AIMessage))
        results: list[ToolMessage] = []
        for index, call in enumerate(ai.tool_calls):
            key = call_key(task.task_id, step, index)
            mcp_name = ctx.names.to_mcp(call["name"])
            if mcp_name is None:
                results.append(
                    ToolMessage(f"Unknown tool {call['name']}.", tool_call_id=call["id"] or key, status="error")
                )
                continue
            text, is_error = await self._run_tool(task, key, mcp_name, call["args"])
            results.append(ToolMessage(text, tool_call_id=call["id"] or key, status="error" if is_error else "success"))
        return {"messages": results}

    async def _run_tool(self, task: TaskRecord, key: str, tool: str, args: dict[str, Any]) -> tuple[str, bool]:
        mark = self._store.get_mark(key)
        if mark is not None and mark.state is MarkState.FINISHED:
            return mark.result or "", mark.is_error
        if mark is not None and mark.state is MarkState.STARTED:
            self._finish(task, key, tool, args, UNKNOWN_OUTCOME, True, "unknown", 0.0)
            return UNKNOWN_OUTCOME, True
        approval = self._store.approval_for_call(key)
        if approval is not None:
            # Every call that has an approval interrupts on every re-run, so LangGraph's positional
            # resume values stay aligned. It returns at once when resumed; the decision is re-read.
            interrupt({"kind": "approval", "approval_id": approval.approval_id})
            approval = self._store.get_approval(approval.approval_id)
        started = time.perf_counter()
        if mark is None:
            self._tool_event(task, key, tool, args, "requested")
        # Conservative: the first leg may run the tool (no approval needed), so it is marked as started.
        self._store.put_mark(CallMark(key, task.task_id, tool, MarkState.STARTED))
        result = await self._tools.call(task.project_id, task.project_folder, tool, args)
        if isinstance(result, InputRequiredResult):
            self._store.put_mark(CallMark(key, task.task_id, tool, MarkState.ASKED))
            action = self._decide(task, key, tool, args, result, approval)
            (request_key,) = (result.input_requests or {"?": None}).keys()
            content: dict[str, Any] | None = {"approve": True} if action == "accept" else None
            self._store.put_mark(CallMark(key, task.task_id, tool, MarkState.STARTED))
            if action == "accept":
                self._tool_event(task, key, tool, args, "running")
            result = await self._tools.call(
                task.project_id,
                task.project_folder,
                tool,
                args,
                input_responses={request_key: ElicitResult(action=action, content=content)},
                request_state=result.request_state,
            )
            if isinstance(result, InputRequiredResult):
                text = "The tool asked for input again; the call was not completed."
                self._finish(task, key, tool, args, text, True, "error", time.perf_counter() - started)
                return text, True
        text, is_error = tool_text(result), bool(result.is_error)
        self._finish(
            task, key, tool, args, text, is_error, "error" if is_error else "ok", time.perf_counter() - started
        )
        return text, is_error

    def _decide(
        self,
        task: TaskRecord,
        key: str,
        tool: str,
        args: dict[str, Any],
        asked: InputRequiredResult,
        approval: Approval | None,
    ) -> Literal["accept", "decline", "cancel"]:
        if approval is not None:
            if approval.status is ApprovalStatus.PENDING:
                log.warning("approval %s resumed while still pending; not running the call", approval.approval_id)
            return approval.mcp_action
        if self._store.has_rule(task.chat_id, tool):
            self._events.publish(
                EventType.APPROVAL_RESOLVED,
                {"call_key": key, "tool": tool, "outcome": "allowed", "by": "allow_always_rule"},
                project_id=task.project_id,
                chat_id=task.chat_id,
                task_id=task.task_id,
            )
            return "accept"
        (request,) = (asked.input_requests or {}).values()
        summary = getattr(request.params, "message", "") or f"Run {tool}"
        now = datetime.now(UTC)
        opened = Approval.open(
            f"ap-{uuid.uuid4().hex[:12]}",
            task.task_id,
            task.chat_id,
            key,
            tool,
            summary,
            args,
            now,
            self._settings.approval_timeout,
        )
        self._store.insert_approval(opened)
        request_model = ApprovalRequest(
            approval_id=opened.approval_id,
            task_id=task.task_id,
            chat_id=task.chat_id,
            tool=tool,
            summary=summary[:2000],
            arguments=args,
            expires_at=opened.expires_at,
        )
        self._events.publish(
            EventType.APPROVAL_REQUESTED,
            request_model.model_dump(mode="json"),
            project_id=task.project_id,
            chat_id=task.chat_id,
            task_id=task.task_id,
        )
        interrupt({"kind": "approval", "approval_id": opened.approval_id})
        resolved = self._store.get_approval(opened.approval_id)
        return resolved.mcp_action if resolved is not None else "cancel"

    def _tool_event(self, task: TaskRecord, key: str, tool: str, args: dict[str, Any], status: str) -> None:
        self._events.publish(
            EventType.TOOL_CALL,
            {"call_key": key, "tool": tool, "arguments": args, "status": status},
            project_id=task.project_id,
            chat_id=task.chat_id,
            task_id=task.task_id,
        )

    def _finish(
        self,
        task: TaskRecord,
        key: str,
        tool: str,
        args: dict[str, Any],
        text: str,
        is_error: bool,
        status: str,
        seconds: float,
    ) -> None:
        self._store.put_mark(CallMark(key, task.task_id, tool, MarkState.FINISHED, text, is_error))
        self._events.publish(
            EventType.TOOL_CALL,
            {
                "call_key": key,
                "tool": tool,
                "arguments": args,
                "status": status,
                "result": text,
                "seconds": round(seconds, 3),
            },
            project_id=task.project_id,
            chat_id=task.chat_id,
            task_id=task.task_id,
        )


CANCELED_RESULT = "Canceled: the task was stopped before this call finished."


def close_dangling_tool_calls(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Add a canceled result for any tool call without one, so the transcript stays valid for the next task."""
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    closed: list[AnyMessage] = []
    for message in messages:
        closed.append(message)
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                if call["id"] and call["id"] not in answered:
                    closed.append(ToolMessage(CANCELED_RESULT, tool_call_id=call["id"], status="error"))
                    answered.add(call["id"])
    return closed
