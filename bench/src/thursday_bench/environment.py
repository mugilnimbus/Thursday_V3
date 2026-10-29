"""What a run was measured on, recorded with every result."""

import hashlib
import importlib.metadata
import pathlib
import platform
import subprocess
import sys
from typing import Any

import psutil

from thursday_bench import fake_model

ROOT = pathlib.Path(__file__).resolve().parents[3]
LIBRARIES = ("fastapi", "uvicorn", "httpx", "websockets", "psutil", "langchain-openai", "a2a-sdk")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()  # noqa: S603, S607


def _cpu_name() -> str:
    try:
        for line in pathlib.Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def _versions() -> dict[str, str]:
    found = {}
    for name in LIBRARIES:
        try:
            found[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return found


def collect(settings: dict[str, Any]) -> dict[str, Any]:
    lock = ROOT / "uv.lock"
    return {
        "commit": _git("rev-parse", "--short", "HEAD"),
        "uncommitted_changes": bool(_git("status", "--short", "--", ".", ":!var", ":!bench/results")),
        "machine": platform.node(),
        "os": f"{platform.system()} {platform.release()}",
        "cpu": _cpu_name(),
        "cpu_threads": psutil.cpu_count(logical=True),
        "memory_gb": round(psutil.virtual_memory().total / 1024**3, 1),
        "python": sys.version.split()[0],
        "libraries": _versions(),
        "uv_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest()[:16] if lock.exists() else "",
        "fake_model": {
            "reply_sha256": hashlib.sha256(fake_model.REPLY.encode()).hexdigest()[:16],
            "reply_characters": len(fake_model.REPLY),
            "stream_pieces": fake_model.PIECES,
        },
        "history_seed": 20261029,
        "settings": settings,
    }


def load_before_run() -> float:
    """CPU use of the whole PC over two seconds, to see that the machine is quiet."""
    return psutil.cpu_percent(interval=2)
