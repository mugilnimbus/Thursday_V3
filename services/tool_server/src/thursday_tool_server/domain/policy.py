"""Permission policy of the built-in tool server.

Fixed in code: shell commands and deletes always ask the user, whatever any prompt says.
Allow-always answers are applied by the main agent (per chat); this server still asks
every time and records the answer it receives.
"""

from enum import StrEnum


class Decision(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class ToolName(StrEnum):
    FS_READ = "fs.read"
    FS_LIST = "fs.list"
    FS_WRITE = "fs.write"
    FS_EDIT = "fs.edit"
    FS_PATCH = "fs.patch"
    FS_DELETE = "fs.delete"
    SHELL = "shell"
    SHELL_SESSION_OPEN = "shell.session.open"
    SHELL_SESSION_EXEC = "shell.session.exec"
    SHELL_SESSION_CLOSE = "shell.session.close"


POLICY: dict[ToolName, Decision] = {
    ToolName.FS_READ: Decision.ALLOW,
    ToolName.FS_LIST: Decision.ALLOW,
    ToolName.FS_WRITE: Decision.ALLOW,
    ToolName.FS_EDIT: Decision.ALLOW,
    ToolName.FS_PATCH: Decision.ALLOW,
    ToolName.FS_DELETE: Decision.ASK,
    ToolName.SHELL: Decision.ASK,
    ToolName.SHELL_SESSION_OPEN: Decision.ALLOW,
    ToolName.SHELL_SESSION_EXEC: Decision.ASK,
    ToolName.SHELL_SESSION_CLOSE: Decision.ALLOW,
}


def decision_for(tool: ToolName) -> Decision:
    return POLICY[tool]
