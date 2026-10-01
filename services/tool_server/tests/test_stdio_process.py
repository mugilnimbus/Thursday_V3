"""The tool server as a real child process over stdio, as the main agent runs it."""

import sys
from typing import Any

import pytest
from mcp.client.client import Client
from mcp.client.stdio import StdioServerParameters
from mcp_types import ElicitResult, InputRequiredResult

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="shell tools target Windows PowerShell")


async def no_auto(context: Any, params: Any) -> Any:
    raise AssertionError("must not auto-elicit")


async def test_stdio_process_round_trip(layout, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("THURSDAY_DATA_DIR", str(tmp_path / "data"))
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "thursday_tool_server", "--workspace", str(layout["ws"]), "--project-id", "p1"],
        env={**__import__("os").environ, "THURSDAY_DATA_DIR": str(tmp_path / "data")},
    )
    async with Client(params, elicitation_callback=no_auto) as client:
        assert client.session.protocol_version == "2026-07-28"  # pyright: ignore[reportAttributeAccessIssue]
        written = await client.call_tool("fs.write", {"path": "out/hello.txt", "content": "hi"})
        assert not written.is_error
        first = await client.session.call_tool(
            "shell", {"command": "Get-Content out/hello.txt"}, allow_input_required=True
        )
        assert isinstance(first, InputRequiredResult) and first.input_requests
        key = next(iter(first.input_requests))
        done = await client.session.call_tool(
            "shell",
            {"command": "Get-Content out/hello.txt"},
            input_responses={key: ElicitResult(action="accept", content={"approve": True})},
            request_state=first.request_state,
            allow_input_required=True,
        )
    assert not isinstance(done, InputRequiredResult)
    assert "hi" in "".join(getattr(c, "text", "") for c in done.content)
    assert (tmp_path / "data" / "services" / "tool_server" / "p1.sqlite").exists()
