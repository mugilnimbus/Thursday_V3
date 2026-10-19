"""Check what Thursday needs on this PC and say plainly what is missing and how to get it.

`thursday check` prints the list; `thursday setup` ends with it; `thursday up` prints only what would stop it from
being useful. Each check is a small function over facts the launcher gathers (which programs exist, which files
exist), so the wording and the rules are tested without touching the machine.
"""

import pathlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

MIN_NODE = 20


class Level(StrEnum):
    OK = "ok"
    MISSING = "missing"  # Thursday will not work, or not fully, until this is fixed
    OPTIONAL = "optional"  # only needed for a part you may not use


@dataclass(frozen=True, slots=True)
class Finding:
    name: str
    level: Level
    detail: str  # what was found, or what is missing
    fix: str = ""  # what to do; empty when nothing is needed


@dataclass(frozen=True, slots=True)
class Facts:
    """What the launcher found on the machine. Everything optional is None or False when absent."""

    env_file: bool
    service_token: bool
    node_version: str | None  # like "v24.1.0"
    npm: bool
    dashboard_built: bool
    dashboard_stale: bool  # the built dashboard is older than its source
    llamacpp: str | None  # the installed build, like "b11146 (cuda-12.4)"
    own_llamacpp_dir: str  # LLAMACPP_DIR, when set
    own_llamacpp_ok: bool
    nvidia: bool
    credential_store: bool
    tailscale: bool
    tailscale_serving: bool | None  # None when it could not be asked
    agents: Sequence[tuple[str, str, bool]] | None  # (agent, provider, its model source answers); None when down
    ports_taken: Sequence[int]  # Thursday's ports held by something that is not Thursday
    speech_models: bool


def node_major(version: str | None) -> int | None:
    try:
        return int((version or "").lstrip("v").split(".")[0])
    except ValueError:
        return None


def findings(f: Facts) -> list[Finding]:
    out: list[Finding] = []

    def add(name: str, ok: bool, found: str, missing: str, fix: str, level: Level = Level.MISSING) -> None:
        out.append(Finding(name, Level.OK, found) if ok else Finding(name, level, missing, fix))

    add(".env settings file", f.env_file, "present", "not created yet", "Run `uv run thursday setup`.")
    add("Service token", f.service_token, "set", "empty", "Run `uv run thursday setup`.")
    major = node_major(f.node_version)
    if f.dashboard_built and not f.dashboard_stale:
        out.append(Finding("Dashboard", Level.OK, "built"))
    elif major is None or not f.npm:
        out.append(
            Finding(
                "Dashboard",
                Level.MISSING,
                "not built, and Node.js is not installed"
                if not f.dashboard_built
                else "out of date, and Node.js is not installed",
                f"Install Node.js {MIN_NODE} or newer from https://nodejs.org, then run "
                "`npm ci --prefix apps/dashboard` and `npm run build --prefix apps/dashboard`.",
            )
        )
    elif major < MIN_NODE:
        out.append(
            Finding(
                "Dashboard",
                Level.MISSING,
                f"Node.js {f.node_version} is too old to build it",
                f"Install Node.js {MIN_NODE} or newer, then build the dashboard.",
            )
        )
    else:
        out.append(
            Finding(
                "Dashboard",
                Level.MISSING,
                "not built" if not f.dashboard_built else "older than its source: an update was not built",
                "Run `npm ci --prefix apps/dashboard` and `npm run build --prefix apps/dashboard`.",
            )
        )
    add(
        "Credential store for API keys",
        f.credential_store,
        "available",
        "this system has none",
        "API keys cannot be saved. On Linux install a Secret Service such as GNOME Keyring; "
        "endpoints that need no key still work.",
    )
    if f.own_llamacpp_dir:
        add(
            "Built-in llama.cpp (your own build)",
            f.own_llamacpp_ok,
            f.own_llamacpp_dir,
            f"no llama-server found in {f.own_llamacpp_dir}",
            "Point LLAMACPP_DIR in .env at the folder that holds llama-server, or clear it and run setup.",
            Level.OPTIONAL,
        )
    else:
        add(
            "Built-in llama.cpp",
            f.llamacpp is not None,
            f.llamacpp or "",
            "not installed",
            "Only needed for the built-in llama.cpp provider. Run `uv run thursday setup` to download it.",
            Level.OPTIONAL,
        )
    out.append(
        Finding("NVIDIA graphics card", Level.OK, "found")
        if f.nvidia
        else Finding(
            "NVIDIA graphics card",
            Level.OPTIONAL,
            "not found (nvidia-smi is not installed)",
            "Other cards work through the Vulkan build of llama.cpp; Monitor shows no GPU memory without NVIDIA.",
        )
    )
    labels = {
        "lmstudio": "LM Studio",
        "llamacpp": "built-in llama.cpp",
        "openai_compatible": "OpenAI-compatible endpoint",
    }
    for agent, provider, reachable in f.agents or ():
        add(
            f"{agent.capitalize()} agent's model",
            reachable,
            f"{labels.get(provider, provider)}, ready",
            f"{labels.get(provider, provider)} is not ready",
            "Open Settings, Agents: check the address and API key (LM Studio, cloud) or the models folder (llama.cpp).",
        )
    if not f.tailscale:
        out.append(
            Finding(
                "Tailscale (for the phone)",
                Level.OPTIONAL,
                "not installed",
                "Only needed for the Android app. Install Tailscale on the PC and the phone.",
            )
        )
    else:
        add(
            "Tailscale (for the phone)",
            bool(f.tailscale_serving),
            "installed and serving the gateway",
            "installed, but the gateway is not published to your tailnet",
            "Run `tailscale serve --bg http://127.0.0.1:8701` (only needed for the Android app).",
            Level.OPTIONAL,
        )
    out.append(
        Finding("Speech models", Level.OK, "downloaded")
        if f.speech_models
        else Finding(
            "Speech models",
            Level.OPTIONAL,
            "not downloaded yet",
            "They download by themselves (about 0.9 GB) the first time you talk or have a reply read aloud.",
        )
    )
    if f.ports_taken:
        taken = ", ".join(str(p) for p in f.ports_taken)
        out.append(
            Finding(
                "Ports",
                Level.MISSING,
                f"in use by another program: {taken}",
                "Close that program, or change the port in .env.",
            )
        )
    else:
        out.append(Finding("Ports", Level.OK, "free or used by Thursday"))
    return out


MARK = {Level.OK: "ok     ", Level.MISSING: "MISSING", Level.OPTIONAL: "note   "}


def report(found: Sequence[Finding], say: Callable[[str], None], *, only_problems: bool = False) -> int:
    """Print the findings. Returns how many things are missing."""
    width = max(len(item.name) for item in found)
    for item in found:
        if only_problems and item.level is not Level.MISSING:
            continue
        say(f"  {MARK[item.level]}  {item.name:<{width}}  {item.detail}")
        if item.fix:
            say(f"           {'':<{width}}  -> {item.fix}")
    missing = sum(1 for item in found if item.level is Level.MISSING)
    if not only_problems:
        say("")
        say(
            "Everything Thursday needs is here."
            if not missing
            else f"{missing} thing(s) need attention before Thursday works fully."
        )
    return missing


def dashboard_stale(dist: pathlib.Path, source: pathlib.Path) -> bool:
    """True when a file under the dashboard's source is newer than the built page."""
    index = dist / "index.html"
    if not index.is_file():
        return False
    built = index.stat().st_mtime
    newest = max((p.stat().st_mtime for p in source.rglob("*") if p.is_file()), default=0.0)
    return newest > built
