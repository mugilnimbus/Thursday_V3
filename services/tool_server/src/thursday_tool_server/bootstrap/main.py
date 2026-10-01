"""Composition root: `python -m thursday_tool_server --workspace <folder> --project-id <id>`.

Started by the main agent as a stdio child process, one per active project. stdout
carries the MCP protocol, so logs go to stderr and the log file only.
"""

import argparse
import contextlib
import re
from collections.abc import AsyncIterator, Sequence

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from thursday_runtime.log_setup import configure_logging
from thursday_runtime.paths import log_dir, service_data_dir
from thursday_runtime.settings import env_file

from thursday_tool_server import __version__
from thursday_tool_server.application.files import FileTools
from thursday_tool_server.application.shell_tools import ShellLimits, ShellTools
from thursday_tool_server.domain.workspace import Workspace
from thursday_tool_server.infrastructure.audit_log import AuditLog
from thursday_tool_server.infrastructure.shell import PersistentShell, run_command
from thursday_tool_server.transport.mcp_server import ToolServer

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


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
    args = parser.parse_args(argv)
    if not _SAFE_ID.match(args.project_id):
        parser.error("project id may contain only letters, digits, '-' and '_'")
    return args


def build(workspace: str, project_id: str, settings: ToolServerSettings) -> tuple[ToolServer, ShellTools, AuditLog]:
    ws = Workspace(workspace)
    audit = AuditLog(service_data_dir("tool_server", settings.thursday_data_dir) / f"{project_id}.sqlite")
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


def main(argv: Sequence[str] | None = None) -> None:
    args = parse(argv)
    settings = ToolServerSettings()
    configure_logging("tool_server", log_dir(settings.thursday_data_dir), settings.log_level)
    server, _, audit = build(args.workspace, args.project_id, settings)
    try:
        server.mcp.run()
    finally:
        audit.close()
