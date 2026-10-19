"""Composition root: `python -m thursday_tool_server --workspace <folder> --project-id <id>`.

Started by the main agent as a stdio child process, one per active project. stdout
carries the MCP protocol, so logs go to stderr and the log file only.

Two one-off commands clean this server's own call logs, for the main agent to run when a chat or a
project is deleted: `forget-chat --chat-id <id>` and `forget-project --project-id <id>`. Each prints one
line of JSON saying what it removed.
"""

import argparse
import contextlib
import json
import re
import sys
from collections.abc import AsyncIterator, Sequence

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from thursday_runtime.log_setup import configure_logging
from thursday_runtime.paths import log_dir, service_data_dir
from thursday_runtime.settings import env_file
from thursday_runtime.sqlite_care import compact_if_worthwhile

from thursday_tool_server import __version__
from thursday_tool_server.application.files import FileTools
from thursday_tool_server.application.shell_tools import ShellLimits, ShellTools
from thursday_tool_server.domain.workspace import Workspace
from thursday_tool_server.infrastructure.audit_log import DEFAULT_KEEP_DAYS, AuditLog, forget_chat, remove_project
from thursday_tool_server.infrastructure.shell import PersistentShell, run_command
from thursday_tool_server.transport.mcp_server import ToolServer

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAINTENANCE = ("forget-chat", "forget-project")


class ToolServerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=env_file(), env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )

    thursday_data_dir: str = ""
    log_level: str = "INFO"
    tool_output_char_limit: int = Field(default=30000, ge=1000)
    shell_default_timeout_seconds: float = Field(default=60, gt=0)
    shell_max_timeout_seconds: float = Field(default=900, gt=0)


def parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="thursday-tool-server")
    parser.add_argument("--workspace", required=True, help="project folder; the sandbox root")
    parser.add_argument("--project-id", required=True, help="project id; names the audit log file")
    parser.add_argument(
        "--keep-days",
        type=int,
        default=DEFAULT_KEEP_DAYS,
        help="days the call log is kept; 0 keeps it until its chat or project is deleted",
    )
    args = parser.parse_args(argv)
    if not _SAFE_ID.match(args.project_id):
        parser.error("project id may contain only letters, digits, '-' and '_'")
    return args


def build(
    workspace: str, project_id: str, settings: ToolServerSettings, keep_days: int = DEFAULT_KEEP_DAYS
) -> tuple[ToolServer, ShellTools, AuditLog]:
    ws = Workspace(workspace)
    log_file = service_data_dir("tool_server", settings.thursday_data_dir) / f"{project_id}.sqlite"
    compact_if_worthwhile(log_file)
    audit = AuditLog(log_file, keep_days)
    limits = ShellLimits(
        settings.shell_default_timeout_seconds, settings.shell_max_timeout_seconds, settings.tool_output_char_limit
    )
    shell = ShellTools(ws, limits, run_command, PersistentShell.start)

    @contextlib.asynccontextmanager
    async def close_sessions_on_exit(_: object) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await shell.close_all()

    files = FileTools(ws, settings.tool_output_char_limit)
    return ToolServer(files, shell, audit, __version__, close_sessions_on_exit), shell, audit


def maintain(argv: Sequence[str], settings: ToolServerSettings) -> dict[str, object]:
    """Run one clean-up command on this server's own call logs and say what was removed."""
    parser = argparse.ArgumentParser(prog="thursday-tool-server")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("forget-chat", help="remove a deleted chat's calls from every project's log").add_argument(
        "--chat-id", required=True
    )
    sub.add_parser("forget-project", help="remove a deleted project's log").add_argument("--project-id", required=True)
    args = parser.parse_args(argv)
    wanted = args.chat_id if args.command == "forget-chat" else args.project_id
    if not _SAFE_ID.match(wanted):
        parser.error("an id may contain only letters, digits, '-' and '_'")
    folder = service_data_dir("tool_server", settings.thursday_data_dir)
    if args.command == "forget-chat":
        return {"removed": forget_chat(folder, wanted)}
    return {"files": remove_project(folder, wanted)}


def main(argv: Sequence[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else list(argv)
    settings = ToolServerSettings()
    if argv and argv[0] in MAINTENANCE:
        print(json.dumps(maintain(argv, settings)))
        return
    args = parse(argv)
    configure_logging("tool_server", log_dir(settings.thursday_data_dir), settings.log_level)
    server, _, audit = build(args.workspace, args.project_id, settings, args.keep_days)
    try:
        server.mcp.run()
    finally:
        audit.close()
