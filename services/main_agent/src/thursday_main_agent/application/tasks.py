"""Task use cases: create, drive, finish, approvals, timeouts, pause and resume.

The A2A transport calls these. Anything that must happen without an incoming request
(an approval timeout, a resume, recovery after a restart) asks the transport to "kick"
the task, which re-enters through the normal execution path.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import messages_to_dict
from thursday_contracts.approvals import ApprovalDecision
from thursday_contracts.events import EventType
from thursday_contracts.task_control import PauseState

from thursday_main_agent.application.ports import Events, TaskRecords
from thursday_main_agent.application.runner import RunOutcome, TaskRunner
from thursday_main_agent.application.worklog import compact_task
from thursday_main_agent.domain.approvals import Approval, ApprovalStatus, TimeoutStreak
from thursday_main_agent.domain.tasks import TaskPhase, TaskRecord

log = logging.getLogger(__name__)
Kick = Callable[[str, dict[str, Any]], Awaitable[None]]
MAX_RESUME_LOOPS = 20


class UnknownTask(Exception):
    pass


RESULT_LIMIT = 8000
CLIPPED_NOTE = "\n\n(Shortened here. The full result is in the task's trace.)"


def clip_result(text: str, limit: int = RESULT_LIMIT) -> str:
    """Keep a result within the limit by ending it at a paragraph or sentence, never mid-word, and say so."""
    if len(text) <= limit:
        return text
    room = text[: limit - len(CLIPPED_NOTE)]
    end = max(room.rfind("\n\n"), room.rfind(". "), room.rfind(".\n"))
    if end < len(room) // 2:
        end = room.rfind(" ")
    return room[: end + 1].rstrip() + CLIPPED_NOTE


class TaskService:
    def __init__(self, store: TaskRecords, events: Events, runner: TaskRunner, timeouts_before_pause: int) -> None:
        self._store = store
        self._events = events
        self._runner = runner
        self._streak_limit = timeouts_before_pause
        self._kick: Kick | None = None
        # The service has one model, and every task shares its window, so only one task runs at a time and
        # the rest wait their turn. A task waiting for an approval has let go of its turn.
        self._model_turn = asyncio.Lock()
        self.running: set[str] = set()

    def set_kick(self, kick: Kick) -> None:
        self._kick = kick

    async def kick(self, task_id: str, action: str, **data: Any) -> None:
        if self._kick is None:
            raise RuntimeError("kick is not wired")
        await self._kick(task_id, {"action": action, **data})

    def _task(self, task_id: str) -> TaskRecord:
        task = self._store.get_task(task_id)
        if task is None:
            raise UnknownTask(task_id)
        return task

    def _state_event(self, task: TaskRecord, **extra: Any) -> None:
        self._events.publish(
            EventType.TASK_STATE,
            {"state": task.phase.value, "pause_state": task.pause_state.value, **extra},
            project_id=task.project_id,
            chat_id=task.chat_id,
            task_id=task.task_id,
        )

    # --- lifecycle -----------------------------------------------------------------------
    def create(
        self,
        task_id: str,
        chat_id: str,
        project_id: str,
        folder: str,
        instruction: str,
        request: str | None = None,
    ) -> TaskRecord:
        """`request` is the name of the request that starts the task. Raises `DuplicateRequest`, with nothing
        recorded or announced, when a task was already started under it."""
        task = TaskRecord(task_id, chat_id, project_id, folder, instruction, datetime.now(UTC))
        self._store.insert_task(task, request)
        self._events.publish(
            EventType.DELEGATION,
            {"instruction": instruction, "project_folder": folder},
            project_id=project_id,
            chat_id=chat_id,
            task_id=task_id,
        )
        self._state_event(task)
        return task

    async def drive(self, task_id: str, *, instruction: str | None = None, resume: object | None = None) -> RunOutcome:
        task = self._task(task_id)
        if instruction is None and resume is None and not await self._runner.has_checkpoint(task_id):
            instruction = task.instruction  # stopped before its first step: start it from the beginning
        self.running.add(task_id)
        try:
            if self._model_turn.locked():
                task.phase = TaskPhase.SUBMITTED
                self._store.save_task(task)
                self._state_event(task, queued=True)
            async with self._model_turn:
                task = self._task(task_id)
                task.phase = TaskPhase.WORKING
                self._store.save_task(task)
                self._state_event(task)
                outcome = await self._run_to_outcome(task, instruction, resume)
        finally:
            self.running.discard(task_id)
        task = self._task(task_id)
        if outcome.kind == "needs_approval":
            task.phase = TaskPhase.INPUT_REQUIRED
            self._store.save_task(task)
            self._state_event(task, approval_id=outcome.approval.approval_id if outcome.approval else None)
        elif outcome.kind == "paused":
            self._state_event(task)
        elif outcome.kind == "completed":
            await self.finish(task, TaskPhase.COMPLETED, outcome.text)
        else:
            await self.finish(task, TaskPhase.FAILED, outcome.text)
        return outcome

    async def _run_to_outcome(self, task: TaskRecord, instruction: str | None, resume: object | None) -> RunOutcome:
        """Run until the task needs something or ends. Whatever goes wrong becomes a failed outcome, never an
        exception, so the task cannot be left looking like it is still working."""
        try:
            outcome = await self._runner.run(task, instruction=instruction, resume=resume)
            for _ in range(MAX_RESUME_LOOPS):
                approval = outcome.approval
                if outcome.kind != "needs_approval" or approval is None or approval.status is ApprovalStatus.PENDING:
                    break
                outcome = await self._runner.run(self._task(task.task_id), resume={"approval_id": approval.approval_id})
            return outcome
        except Exception as exc:
            log.exception("task %s stopped on an unexpected error", task.task_id)
            return RunOutcome(
                "failed",
                f"The task stopped on an unexpected error ({type(exc).__name__}: {str(exc)[:300]}). "
                "The details are in the main agent's log.",
            )

    async def finish(self, task: TaskRecord, phase: TaskPhase, text: str) -> None:
        if not task.transcript_saved:
            work = compact_task(task.instruction, await self._runner.task_messages(task), phase, clip_result(text))
            self._store.append_transcript(task.chat_id, task.task_id, messages_to_dict(work))
            kept = await self._runner.task_summary(task)
            if kept is not None and kept[1] > task.history_len:
                # The summary was written mid-task, so it covers part of this task as well as the history. The
                # transcript now holds this task as two compact messages, so the summary is saved as covering the
                # history only; the task's own record follows it in full and nothing is lost.
                self._store.save_chat_summary(task.chat_id, task.history_len, kept[0])
        for approval in self._store.pending_approvals(task.task_id):
            approval.cancel()
            self._store.save_approval(approval)
            self._publish_resolved(approval, "system")
        task = self._task(task.task_id)
        task.phase = phase
        task.pause_state = PauseState.NONE
        self._store.save_task(task)
        self._store.mark_ended(task.task_id, datetime.now(UTC))  # the retention period counts from here
        self._state_event(task, summary=clip_result(text))
        if phase is not TaskPhase.CANCELED:
            title = "Task finished" if phase is TaskPhase.COMPLETED else "Task failed"
            self._events.publish(
                EventType.NOTIFICATION,
                {"title": title, "body": text[:500], "kind": phase.value},
                project_id=task.project_id,
                chat_id=task.chat_id,
                task_id=task.task_id,
            )

    async def canceled(self, task_id: str) -> None:
        task = self._store.get_task(task_id)
        if task is not None and not task.terminal:
            await self.finish(task, TaskPhase.CANCELED, "Stopped by the user.")

    def recoverable(self) -> list[TaskRecord]:
        """Tasks that were running when the process stopped and should continue now."""
        return [
            t
            for t in self._store.open_tasks()
            if t.phase in (TaskPhase.SUBMITTED, TaskPhase.WORKING) and t.pause_state is not PauseState.PAUSED
        ]

    # --- approvals -----------------------------------------------------------------------
    def answer_approval(self, approval_id: str, decision: ApprovalDecision, by: str) -> Approval:
        """First answer wins; raises ApprovalAlreadyResolved or KeyError."""
        approval = self._store.answer_approval(approval_id, decision, by, datetime.now(UTC))
        task = self._task(approval.task_id)
        streak = TimeoutStreak(self._streak_limit, task.timeout_streak)
        streak.record(approval.status)
        task.timeout_streak = streak.count
        self._store.save_task(task)
        self._publish_resolved(approval, by)
        return approval

    def expire_due(self) -> list[str]:
        """Time out overdue approvals. Returns the tasks to kick so they can continue."""
        now = datetime.now(UTC)
        kicked: list[str] = []
        for approval in self._store.pending_approvals():
            if not approval.is_due(now):
                continue
            approval.expire()
            self._store.save_approval(approval)
            task = self._task(approval.task_id)
            streak = TimeoutStreak(self._streak_limit, task.timeout_streak)
            if streak.record(ApprovalStatus.TIMED_OUT):
                task.auto_pause()
                self._events.publish(
                    EventType.NOTIFICATION,
                    {
                        "title": "Task paused",
                        "kind": "auto_pause",
                        "body": f"No answer to {streak.count} approval requests in a row, so the task was paused.",
                    },
                    project_id=task.project_id,
                    chat_id=task.chat_id,
                    task_id=task.task_id,
                )
            task.timeout_streak = streak.count
            self._store.save_task(task)
            self._publish_resolved(approval, "timeout")
            kicked.append(task.task_id)
        return kicked

    def _publish_resolved(self, approval: Approval, by: str) -> None:
        self._events.publish(
            EventType.APPROVAL_RESOLVED,
            {
                "approval_id": approval.approval_id,
                "call_key": approval.call_key,
                "tool": approval.tool,
                "outcome": approval.status.value,
                "decision": approval.decision.value if approval.decision else None,
                "by": by,
            },
            chat_id=approval.chat_id,
            task_id=approval.task_id,
        )

    # --- pause and resume ----------------------------------------------------------------
    def pause(self, task_id: str) -> PauseState:
        task = self._task(task_id)
        state = task.request_pause()
        self._store.save_task(task)
        self._state_event(task)
        return state

    def resume(self, task_id: str) -> tuple[PauseState, bool]:
        """Returns the new state and whether the task must be kicked to continue."""
        task = self._task(task_id)
        wake = task.request_resume() and task.phase is TaskPhase.WORKING and task_id not in self.running
        self._store.save_task(task)
        self._state_event(task)
        return task.pause_state, wake


async def approval_timer(service: TaskService, stop: asyncio.Event, interval: float = 1.0) -> None:
    """Expires overdue approvals and kicks their tasks so the model hears "no response"."""
    while not stop.is_set():
        for task_id in service.expire_due():
            try:
                await service.kick(task_id, "approval_timeout")
            except Exception:
                log.exception("could not continue task %s after an approval timeout", task_id)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval)
