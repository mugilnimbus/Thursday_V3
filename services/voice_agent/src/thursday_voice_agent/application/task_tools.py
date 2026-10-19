"""The tools the voice model may call: handing work to the main agent, and controlling this chat's tasks."""

from typing import Any

from thursday_voice_agent.application.errors import MainAgentRefused, MainAgentUnavailable
from thursday_voice_agent.application.tasks import TaskRelay


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


async def run_tool(
    relay: TaskRelay,
    name: str,
    args: dict[str, Any],
    chat_id: str,
    project_id: str,
    project_folder: str,
    request: str | None = None,
) -> str:
    """Carry out one tool call and say what happened, in words the model reads back to the user. `request` is the
    name a task is started under, when this call starts one."""
    try:
        if name == "delegate_task":
            instruction = str(args.get("instruction", "")).strip()
            if not instruction:
                return "No instruction given."
            task = await relay.delegate(chat_id, project_id, project_folder, instruction, request=request)
            return f"Task {task.task_id[:8]} started."
        if name == "list_tasks":
            return relay.describe(chat_id)
        if name in ("pause_task", "resume_task", "stop_task"):
            return await relay.control(chat_id, name.removesuffix("_task"), args.get("task_id"))
    except MainAgentUnavailable:
        return "The main agent is not reachable right now."
    except MainAgentRefused as exc:
        return f"The main agent refused: {exc}"
    return f"Unknown tool {name}."
