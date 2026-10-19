"""Names of the values Thursday sends beside a tool call's arguments (MCP `_meta`).

They travel with the call, the model never sees them, and a tool never acts on them. The tool server records
the chat a call belongs to, so that deleting the chat can remove the call from its log.
"""

import re

CHAT_ID_META_KEY = "app.thursday/chat_id"
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def chat_id_from(meta: object) -> str | None:
    """The chat id in a call's metadata, if there is a well-formed one."""
    value = meta.get(CHAT_ID_META_KEY) if isinstance(meta, dict) else None
    return value if isinstance(value, str) and _ID.match(value) else None
