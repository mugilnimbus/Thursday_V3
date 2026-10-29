"""Set up this project on a new machine, step by step.

    python scripts/setup.py          guided: explains each step and asks for each setting
    python scripts/setup.py --yes    no questions: uses the values in .env.example (CI uses this)

It checks the tools this project needs, creates .env from .env.example, installs the
dependencies, prepares the development data, and checks that the project runs. It is
safe to run again: it keeps an existing .env and repeats only what is needed.
Needs only Python 3.9+, on Windows, Linux, or macOS.
"""

import getpass
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------- project settings: edit these
PROJECT = "Thursday"

# The tools a new user must have: (command, minimum version or None, where to get it).
REQUIREMENTS = [
    ("python", "3.12", "https://www.python.org/downloads/"),
    ("uv", None, "https://docs.astral.sh/uv/getting-started/installation/"),
    ("git", None, "https://git-scm.com/downloads"),
    ("node", "20", "https://nodejs.org/en/download"),
]
if sys.platform != "win32":
    # The tool server runs shell commands in PowerShell; Windows has it, Linux and macOS need PowerShell 7.
    REQUIREMENTS.append(
        ("pwsh", None, "https://learn.microsoft.com/powershell/scripting/install/installing-powershell")
    )

# The setup steps, in order: (what it does, the command).
STEPS = [
    ("Install the dependencies", ["uv", "sync"]),
    ("Install the dashboard packages", ["npm", "ci", "--prefix", "apps/dashboard"]),
    ("Build the dashboard", ["npm", "run", "build", "--prefix", "apps/dashboard"]),
    # Makes the service token. It leaves out the 650 MB llama.cpp download: run `uv run thursday setup` for that.
    ("Create the service token", ["uv", "run", "thursday", "setup", "--skip-llamacpp"]),
]

# The settings worth asking about in guided mode. Every other setting takes its example value from .env.example,
# and Settings in the dashboard changes most of them later. The service token is made by the step above.
ASK_FOR = ["VOICE_LLM_BASE_URL", "MAIN_LLM_BASE_URL", "LLAMACPP_MODELS_DIR"]

# One command that shows the project runs. Leave it as None until there is one.
HEALTH = ["uv", "run", "thursday", "check"]

# What to tell the user at the end.
NEXT = [
    "Optional: the built-in llama.cpp (about 650 MB):  uv run thursday setup",
    "Run it:    uv run thursday up",
    "Open it:   http://127.0.0.1:8700, then Settings, Agents",
    "Check it:  python scripts/check.py",
]
# ---------------------------------------------------------------- end of project settings

SECRET = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD)", re.I)


def say(text: str = "") -> None:
    print(text, flush=True)


def stop(problem: str, fix: str) -> None:
    say(f"\n  Stopped: {problem}")
    say(f"  To fix it: {fix}")
    say("  Then run this setup again.")
    sys.exit(1)


def version_of(command: str) -> str:
    try:
        out = subprocess.run([command, "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    found = re.search(r"\d+(\.\d+)+", out.stdout + out.stderr)
    return found.group(0) if found else ""


def at_least(have: str, need: str) -> bool:
    as_tuple = lambda v: tuple(int(x) for x in v.split("."))
    width = max(len(have.split(".")), len(need.split(".")))
    pad = lambda t: t + (0,) * (width - len(t))
    return pad(as_tuple(have)) >= pad(as_tuple(need))


def check_tools() -> None:
    say("1. Checking the tools this project needs")
    for command, minimum, url in REQUIREMENTS:
        name = command
        if command == "python":
            have = ".".join(str(x) for x in sys.version_info[:3])
        else:
            if not shutil.which(command):
                stop(f"{name} is not installed.", f"install it from {url}")
            have = version_of(command)
        if minimum and have and not at_least(have, minimum):
            stop(f"{name} {have} is installed, and this project needs {minimum} or newer.", f"update it from {url}")
        say(f"   ok  {name} {have}".rstrip())


def read_example() -> list:
    """The settings in .env.example: (name, example value, description)."""
    example = ROOT / ".env.example"
    if not example.exists():
        return []
    rows = []
    for line in example.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, rest = line.split("=", 1)
        value, _, note = rest.partition("#")
        rows.append((name.strip(), value.strip(), note.strip()))
    return rows


def make_env(ask: bool) -> None:
    say("\n2. Creating your settings file (.env)")
    env = ROOT / ".env"
    rows = read_example()
    if env.exists():
        say("   ok  .env already exists, so it is kept as it is")
        return
    if not rows:
        say("   ok  this project needs no settings")
        return
    lines = []
    for name, example, note in rows:
        value = example
        if ask and name in ASK_FOR:
            say(f"\n   {name}: {note or 'no description'}")
            prompt = f"   Value for {name}" + (f" [{example}]" if example else "") + ": "
            answer = getpass.getpass(prompt) if SECRET.search(name) else input(prompt)
            value = answer.strip() or example
        if not value and name in ASK_FOR:
            say(
                f"   note  {name} is empty. Set it in Settings in the dashboard, or in .env, before you use the parts that need it."
            )
        lines.append(f"{name}={value}")
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    say("\n   ok  .env created. It holds your own values and is never committed.")


def run_steps() -> None:
    say("\n3. Installing and preparing")
    (ROOT / "var").mkdir(exist_ok=True)
    for what, command in STEPS:
        say(f"   ...  {what}: {' '.join(command)}")
        if not shutil.which(command[0]):
            stop(f"the command {command[0]} is not found.", f"install {command[0]}, then open a new terminal")
        result = subprocess.run(
            [shutil.which(command[0]) or command[0], *command[1:]], cwd=ROOT
        )  # the full path finds npm.cmd on Windows
        if result.returncode != 0:
            stop(
                f'"{what}" failed (exit code {result.returncode}).',
                "read the error above; the README's Troubleshooting section lists the usual causes",
            )
        say(f"   ok  {what}")


def check_health() -> None:
    say("\n4. Checking that it runs")
    if not HEALTH:
        say("   skip  no health check is set up yet")
        return
    result = subprocess.run([shutil.which(HEALTH[0]) or HEALTH[0], *HEALTH[1:]], cwd=ROOT)
    if result.returncode != 0:
        stop("the project did not start correctly.", "read the error above, and check the values in .env")
    say("   ok  it runs")


def main() -> None:
    ask = "--yes" not in sys.argv and not os.environ.get("CI") and sys.stdin.isatty()
    say(f"Setting up {PROJECT}. Each step says what it does.\n")
    check_tools()
    make_env(ask)
    run_steps()
    check_health()
    say(f"\nDone. {PROJECT} is set up.")
    for line in NEXT:
        say(f"   {line}")


if __name__ == "__main__":
    main()
