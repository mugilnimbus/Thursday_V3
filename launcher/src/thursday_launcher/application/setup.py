"""First-run setup: create `.env` from the example if missing, and generate the service token.

Only the `THURSDAY_SERVICE_TOKEN` line is changed; every other line is kept as is. The token
is never printed.
"""

import os
import re
import secrets
import tempfile
from pathlib import Path

TOKEN_KEY = "THURSDAY_SERVICE_TOKEN"  # noqa: S105 - the variable name, not a secret
_LINE = re.compile(rf"^\s*{TOKEN_KEY}\s*=\s*(.*)$")


def ensure_env(env_path: Path, example_path: Path) -> list[str]:
    """Returns short notes about what was done."""
    notes: list[str] = []
    if not env_path.exists():
        if not example_path.exists():
            raise FileNotFoundError(f"neither {env_path.name} nor {example_path.name} exists")
        env_path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")
        notes.append(f"created {env_path.name} from {example_path.name}")
    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    token = secrets.token_urlsafe(32)
    found = False
    for index, line in enumerate(lines):
        match = _LINE.match(line.rstrip("\r\n"))
        if match is None:
            continue
        found = True
        if match.group(1).strip():
            notes.append("service token already set; left unchanged")
            return notes
        ending = "\r\n" if line.endswith("\r\n") else "\n"
        lines[index] = f"{TOKEN_KEY}={token}{ending}"
    if not found:
        lines.append(("" if not lines or lines[-1].endswith("\n") else "\n") + f"{TOKEN_KEY}={token}\n")
    _atomic_write(env_path, "".join(lines))
    notes.append("generated a new service token")
    return notes


def _atomic_write(path: Path, text: str) -> None:
    handle, temp = tempfile.mkstemp(dir=path.parent, prefix=".env.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as file:
            file.write(text)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
