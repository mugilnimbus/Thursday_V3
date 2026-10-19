import asyncio
import subprocess
import sys
import time

import pytest
from thursday_tool_server.infrastructure.shell import PersistentShell, run_command

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows process-tree behavior")


def ping_processes() -> int:
    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq PING.EXE", "/FO", "CSV", "/NH"], capture_output=True, text=True
    ).stdout
    return sum(1 for line in out.splitlines() if line.lower().startswith('"ping.exe"'))


async def test_timeout_kills_the_whole_tree_and_keeps_partial_output(tmp_path) -> None:
    before = ping_processes()
    started = time.monotonic()
    result = await run_command("'started'; cmd /c ping -n 30 127.0.0.1", tmp_path, timeout=3, output_limit=10000)
    assert result.timed_out and time.monotonic() - started < 10
    assert "started" in result.output
    await asyncio.sleep(0.5)
    assert ping_processes() <= before, "grandchild ping.exe survived the timeout"


async def test_cancellation_kills_the_tree(tmp_path) -> None:
    before = ping_processes()
    task = asyncio.create_task(run_command("cmd /c ping -n 30 127.0.0.1", tmp_path, timeout=60, output_limit=1000))
    await asyncio.sleep(2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.5)
    assert ping_processes() <= before


async def test_exit_code_and_output_cap(tmp_path) -> None:
    result = await run_command("'x' * 5000; exit 3", tmp_path, timeout=30, output_limit=100)
    assert result.exit_code == 3 and result.truncated and len(result.output) == 100


async def test_session_timeout_closes_the_session(tmp_path) -> None:
    shell = await PersistentShell.start(tmp_path)
    result = await shell.run("Start-Sleep -Seconds 30", timeout=2, output_limit=1000)
    assert result.timed_out and not shell.alive


async def test_a_powershell_error_in_a_session_is_not_reported_as_success(tmp_path) -> None:
    shell = await PersistentShell.start(tmp_path)
    try:
        failed = await shell.run("throw 'it broke'", timeout=20, output_limit=2000)
        assert failed.exit_code == 1 and "it broke" in failed.output
        missing = await shell.run("no-such-command-here", timeout=20, output_limit=2000)
        assert missing.exit_code == 1
        native = await shell.run("cmd /c exit 7", timeout=20, output_limit=2000)
        assert native.exit_code == 7, "a program's own exit code is kept"
        fine = await shell.run("Write-Output 'ok'", timeout=20, output_limit=2000)
        assert fine.exit_code == 0 and "ok" in fine.output, "and one failure does not stick to the next command"
    finally:
        await shell.close()
