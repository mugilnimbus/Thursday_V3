"""Run every check this project has, in order, and say which one failed.

    python scripts/check.py

Exit code 0 when every check passes, 1 when one fails. CI runs this same file.
Needs only Python 3.9+, on Windows, Linux, or macOS.
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------- project settings: edit these
# The checks, in order: (what it checks, the command).
CHECKS = [
    ("Lint", ["uv", "run", "ruff", "check", "."]),
    ("Types", ["uv", "run", "pyright"]),
    # The same type check as Windows, so Windows-only problems show before CI runs.
    ("Types as Windows", ["uv", "run", "pyright", "--pythonplatform", "Windows"]),
    ("Tests", ["uv", "run", "pytest", "-q"]),
    ("Architecture model", ["node", "docs/architecture/check.mjs"]),
    ("Dashboard types", ["npm", "run", "check", "--prefix", "apps/dashboard"]),
    ("Dashboard tests", ["npm", "test", "--prefix", "apps/dashboard"]),
]
# ---------------------------------------------------------------- end of project settings


def main() -> None:
    failed = []
    for what, command in CHECKS:
        print(f"\n== {what}: {' '.join(command)}", flush=True)
        if not shutil.which(command[0]):
            print(f"   {command[0]} is not found. Run python scripts/setup.py first.")
            failed.append(what)
            continue
        if (
            subprocess.run([shutil.which(command[0]), *command[1:]], cwd=ROOT).returncode != 0
        ):  # the full path finds npm.cmd on Windows
            failed.append(what)
    print()
    if failed:
        print(f"Failed: {', '.join(failed)}. The output above each one shows why.")
        sys.exit(1)
    print(f"All {len(CHECKS)} checks passed.")


if __name__ == "__main__":
    main()
