"""The MCP contract the main agent relies on, exercised through a real MCP client (in-process)."""

import sqlite3
import sys
from typing import Any, Literal

import pytest
from mcp.client.client import Client
from mcp_types import ElicitResult, InputRequiredResult
from thursday_tool_server.bootstrap.main import ToolServerSettings, build
from thursday_tool_server.domain.policy import POLICY, Decision

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="shell tools target Windows PowerShell")


async def refuse_auto_elicitation(context, params):
    raise AssertionError("the main agent answers approvals itself; the SDK must not auto-elicit")


@pytest.fixture
def server(layout, tmp_path):
    settings = ToolServerSettings(
        thursday_data_dir=str(tmp_path / "data"),
        tool_output_char_limit=5000,
        shell_default_timeout_seconds=20,
        shell_max_timeout_seconds=30,
    )
    tool_server, _, audit = build(str(layout["ws"]), "proj-1", settings)
    yield tool_server
    audit.close()


def text(result) -> str:
    return "".join(getattr(c, "text", "") for c in result.content)


def audit_rows(tmp_path) -> list[tuple[str, str, str]]:
    db = sqlite3.connect(tmp_path / "data" / "services" / "tool_server" / "proj-1.sqlite")
    try:
        return db.execute("select tool, permission, outcome from calls order by id").fetchall()
    finally:
        db.close()


async def test_tool_list_matches_policy_and_hides_the_approval_parameter(server) -> None:
    async with Client(server.mcp, elicitation_callback=refuse_auto_elicitation) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == {name.value for name in POLICY}
    for tool in tools.values():
        assert "approval" not in (tool.input_schema.get("properties") or {})


@pytest.mark.parametrize("tool", [name for name, d in POLICY.items() if d is Decision.ASK])
async def test_every_ask_tool_returns_input_required_first(server, tool) -> None:
    arguments = {
        "fs.delete": {"path": "notes.txt"},
        "shell": {"command": "echo hi"},
        "shell.session.exec": {"handle": "sh-none", "command": "echo hi"},
    }[tool.value]
    async with Client(server.mcp, elicitation_callback=refuse_auto_elicitation) as client:
        first = await client.session.call_tool(tool.value, arguments, allow_input_required=True)
    assert isinstance(first, InputRequiredResult)
    assert first.input_requests is not None
    (request,) = first.input_requests.values()
    assert request.method == "elicitation/create"


async def answer(client, tool: str, arguments: dict, action: Literal["accept", "decline", "cancel"]) -> Any:
    first = await client.session.call_tool(tool, arguments, allow_input_required=True)
    assert isinstance(first, InputRequiredResult)
    assert first.input_requests is not None
    key = next(iter(first.input_requests))
    content: dict[str, Any] | None = {"approve": True} if action == "accept" else None
    return await client.session.call_tool(
        tool,
        arguments,
        input_responses={key: ElicitResult(action=action, content=content)},
        request_state=first.request_state,
        allow_input_required=True,
    )


async def test_delete_runs_only_after_accept(server, layout, tmp_path) -> None:
    async with Client(server.mcp, elicitation_callback=refuse_auto_elicitation) as client:
        declined = await answer(client, "fs.delete", {"path": "notes.txt"}, "decline")
        assert "denied" in text(declined) and (layout["ws"] / "notes.txt").exists()
        no_answer = await answer(client, "fs.delete", {"path": "notes.txt"}, "cancel")
        assert "did not respond" in text(no_answer) and (layout["ws"] / "notes.txt").exists()
        accepted = await answer(client, "fs.delete", {"path": "notes.txt"}, "accept")
        assert "deleted file notes.txt" in text(accepted) and not (layout["ws"] / "notes.txt").exists()
    assert audit_rows(tmp_path) == [
        ("fs.delete", "ask:declined", "not_run"),
        ("fs.delete", "ask:no_response", "not_run"),
        ("fs.delete", "ask:accepted", "ok"),
    ]


async def test_shell_runs_in_the_workspace_after_accept(server, layout) -> None:
    async with Client(server.mcp, elicitation_callback=refuse_auto_elicitation) as client:
        result = await answer(client, "shell", {"command": "(Get-Location).Path; 'ünïcode'"}, "accept")
    output = text(result)
    assert "exit code: 0" in output and str(layout["ws"]).lower() in output.lower() and "ünïcode" in output


async def test_sandbox_violation_is_a_tool_error_the_model_can_read(server, tmp_path) -> None:
    async with Client(server.mcp, elicitation_callback=refuse_auto_elicitation) as client:
        result = await client.call_tool("fs.read", {"path": "../outside/secret.txt"})
    assert result.is_error and "outside_workspace" in text(result)
    assert audit_rows(tmp_path)[-1][2] == "error"


async def test_session_keeps_state_between_commands(server, layout) -> None:
    (layout["ws"] / "sub").mkdir()
    async with Client(server.mcp, elicitation_callback=refuse_auto_elicitation) as client:
        handle = text(await client.call_tool("shell.session.open", {}))
        await answer(client, "shell.session.exec", {"handle": handle, "command": "$x = 21; Set-Location sub"}, "accept")
        result = await answer(
            client, "shell.session.exec", {"handle": handle, "command": "$x * 2\n(Get-Location).Path"}, "accept"
        )
        await client.call_tool("shell.session.close", {"handle": handle})
    out = text(result)
    assert "42" in out and out.lower().rstrip().endswith("sub")
