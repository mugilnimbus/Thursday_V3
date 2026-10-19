"""The agent loop: a LangGraph graph with an LLM step and a tools step, one thread per task.

- Pause lands at the start of the LLM step (a step is one LLM call plus its tool calls).
- The LLM step keeps the model's view inside its window: older messages are summarised before a call when the
  view is near the limit, and harder after a call that overflowed (`model_call` makes the call itself).
- The tools step runs each call at most once and asks the user first when a tool wants that (`tool_step`).
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Annotated, Any, Literal, NotRequired, TypedDict, cast

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    messages_from_dict,
)
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, interrupt
from thursday_contracts.events import EventType
from thursday_llm.runtime import LlmRuntime

from thursday_main_agent.application.compaction import (
    HARDER_KEEP_FRACTION,
    KEEP_FRACTION,
    Compactor,
    estimate_tokens,
    summary_message,
)
from thursday_main_agent.application.model_call import OVERFLOW_MESSAGES, LlmUnavailable, ModelCalls, ModelOverflow
from thursday_main_agent.application.ports import Events, LoopRecords, ToolServers
from thursday_main_agent.application.tool_step import ToolCalls
from thursday_main_agent.domain.approvals import Approval
from thursday_main_agent.domain.tasks import TaskRecord
from thursday_main_agent.domain.tool_calls import ToolNameMap, call_key

log = logging.getLogger(__name__)
TOOL_SCHEMA_TOKENS = 1500  # rough allowance for tool definitions sent with every call


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


class TaskRunner:
    def __init__(
        self,
        store: LoopRecords,
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
        self._system_prompt = system_prompt
        self._contexts: dict[str, _RunContext] = {}
        self._checkpointer = checkpointer
        self._model = ModelCalls(llm, events, settings.llm_retries, settings.retry_base_delay)
        self._tool_calls = ToolCalls(store, events, tools, settings.approval_timeout)
        self._compactor = Compactor(self._model.summarise, settings.compaction_threshold_percent)
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

    @property
    def last_llm(self) -> dict[str, Any]:
        """Speed and context use of the last successful model call, for the service's status."""
        return self._model.last_llm

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

    async def task_summary(self, task: TaskRecord) -> tuple[str, int] | None:
        """The running summary this task ended with and how many messages it covers, if it wrote one."""
        snapshot = await self._graph.aget_state({"configurable": {"thread_id": task.task_id}})
        summary = snapshot.values.get("summary", "") if snapshot.values else ""
        return (summary, snapshot.values.get("summary_upto", 0)) if summary else None

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
        summary, upto = state.get("summary", ""), state.get("summary_upto", 0)
        updates = await self._compact_if_needed(task, state, summary, upto, step)
        summary, upto = updates.get("summary", summary), updates.get("summary_upto", upto)
        try:
            view = self._view(summary, upto, state["messages"], task.history_len)
            message = await self._model.reply(task, view, ctx.llm_tools, step)
        except ModelOverflow as first:
            # A full window or a cut-off tool call: compact harder and try once more, then give up clearly.
            updates.update(await self._compact_if_needed(task, state, summary, upto, step, harder=True))
            summary, upto = updates.get("summary", summary), updates.get("summary_upto", upto)
            try:
                view = self._view(summary, upto, state["messages"], task.history_len)
                message = await self._model.reply(task, view, ctx.llm_tools, step, attempt_offset=first.attempt)
            except ModelOverflow as second:
                raise LlmUnavailable(OVERFLOW_MESSAGES[second.kind]) from second
        return {"messages": [message], **updates}

    def _view(self, summary: str, upto: int, messages: list[AnyMessage], history_len: int) -> list[AnyMessage]:
        """What the model sees: system prompt, summary, the current instruction (always verbatim), recent messages."""
        head: list[AnyMessage] = [SystemMessage(self._system_prompt())]
        if summary:
            head.append(summary_message(summary))
        if upto > history_len < len(messages):
            head.append(messages[history_len])
        return [*head, *messages[upto:]]

    async def _compact_if_needed(
        self, task: TaskRecord, state: State, summary: str, upto: int, step: int, *, harder: bool = False
    ) -> dict[str, Any]:
        """Summarise older messages when the view is near the window (always, and keeping less, when `harder`)."""
        if not await self._model.note_window():
            return {}
        context_length = self._model.context_length
        view_tokens = (
            estimate_tokens(self._view(summary, upto, state["messages"], task.history_len)) + TOOL_SCHEMA_TOKENS
        )
        chosen = self._llm.config.compact_at_tokens
        # A cloud endpoint reports no window: the chosen token count then stands in for it.
        window = context_length or chosen
        if window is None or not (harder or self._compactor.needed(view_tokens, context_length, chosen)):
            return {}
        try:
            result = await self._compactor.compact(
                state["messages"],
                summary,
                upto,
                window,
                HARDER_KEEP_FRACTION if harder else KEEP_FRACTION,
            )
        except Exception as exc:  # the summariser is the model too: its failure must not crash the task
            log.warning("compaction failed: %s: %s", type(exc).__name__, exc)
            if harder:
                raise LlmUnavailable(
                    f"The model's context is full and it could not be summarised ({type(exc).__name__}). "
                    "Load the model with a larger context length, or split the work into smaller tasks."
                ) from exc
            return {}
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
                "context_length": context_length,
                "summarised_messages": result.summarised_messages,
                "summary": result.summary,
                "harder": harder,
                "from_digest": result.from_digest,
            },
            project_id=task.project_id,
            chat_id=task.chat_id,
            task_id=task.task_id,
        )
        return {"summary": result.summary, "summary_upto": result.upto}

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
            text, is_error = await self._tool_calls.run(task, key, mcp_name, call["args"])
            results.append(ToolMessage(text, tool_call_id=call["id"] or key, status="error" if is_error else "success"))
        return {"messages": results}


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
