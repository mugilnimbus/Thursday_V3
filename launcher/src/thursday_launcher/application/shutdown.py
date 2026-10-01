"""`thursday down`: stop everything that `thursday up` started, from any terminal.

Two steps. First ask the running supervisor to stop by creating a small request file it watches;
it then shuts the services down cleanly. Then, for any service still answering (one left behind by
a supervisor that was killed), stop the process that holds its port.
"""

import asyncio
import pathlib
from collections.abc import Sequence
from typing import Protocol

from thursday_launcher.domain.supervision import ServiceSpec

STOP_FILE = "launcher.stop"
PID_FILE = "launcher.pid"


class Probe(Protocol):
    async def is_healthy(self, spec: ServiceSpec) -> bool: ...


class PortKiller(Protocol):
    def kill(self, port: int) -> bool:
        """Stop the process listening on the port (and its children). True if one was found."""
        ...

    def kill_pid(self, pid: int) -> bool:
        """Stop a process and its children. True if it was running."""
        ...


def record_supervisor(data_root: pathlib.Path, pid: int) -> None:
    (data_root / PID_FILE).write_text(str(pid), encoding="utf-8")


def forget_supervisor(data_root: pathlib.Path) -> None:
    (data_root / PID_FILE).unlink(missing_ok=True)


def supervisor_pid(data_root: pathlib.Path) -> int | None:
    try:
        return int((data_root / PID_FILE).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def stop_requested(data_root: pathlib.Path) -> bool:
    return (data_root / STOP_FILE).exists()


def clear_stop_request(data_root: pathlib.Path) -> None:
    (data_root / STOP_FILE).unlink(missing_ok=True)


async def shut_down(
    specs: Sequence[ServiceSpec],
    data_root: pathlib.Path,
    probe: Probe,
    killer: PortKiller,
    wait_seconds: float = 20.0,
    interval: float = 0.5,
) -> dict[str, str]:
    """Returns what happened to each service: "was not running", "stopped", or "force stopped"."""

    async def running() -> list[ServiceSpec]:
        health = await asyncio.gather(*(probe.is_healthy(s) for s in specs))
        return [s for s, up in zip(specs, health, strict=True) if up]

    up_before = await running()
    outcome = {str(s.name): "was not running" for s in specs}
    if not up_before:
        return outcome
    request = data_root / STOP_FILE
    request.write_text("stop", encoding="utf-8")
    try:
        waited = 0.0
        still = up_before
        while still and waited < wait_seconds:
            await asyncio.sleep(interval)
            waited += interval
            still = await running()
    finally:
        clear_stop_request(data_root)
    for spec in up_before:
        outcome[str(spec.name)] = "stopped"
    if still:
        # The supervisor did not react (it was killed, or is an older version): stop it first so it
        # cannot restart the services, then stop each service that is left.
        pid = supervisor_pid(data_root)
        if pid is not None:
            killer.kill_pid(pid)
        forget_supervisor(data_root)
    for spec in still:
        outcome[str(spec.name)] = "force stopped" if killer.kill(spec.port) else "could not be stopped"
    return outcome
