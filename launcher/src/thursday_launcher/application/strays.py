"""Stop llama.cpp servers that an agent left behind.

An agent starts its own `llama-server` and stops it when it unloads or shuts down. If the agent dies without doing
that (a crash, a forced stop), the server keeps running and keeps the GPU memory. Each server's process number is
written to `llama-<owner>.pid` in the logs folder when it starts; the launcher reads those before it starts an agent
and after it stops everything, and stops what is still there.
"""

import pathlib
from collections.abc import Iterable, Sequence
from typing import Protocol

# Which service owns which record: the agents name their servers "voice" and "main".
OWNERS = {"voice_agent": "voice", "main_agent": "main"}


class LlamaStopper(Protocol):
    def stop_llama(self, pid: int, folders: Sequence[pathlib.Path]) -> bool:
        """Stop the process if it is a llama.cpp server run from one of the folders. True if one was stopped.

        The folder check matters: a recorded number can be reused by another program, and LM Studio runs
        llama.cpp servers of its own, which are never Thursday's to stop.
        """
        ...

    def llama_under(self, folders: Sequence[pathlib.Path]) -> list[int]:
        """Process numbers of llama.cpp servers whose program file is inside one of the folders."""
        ...


def _record(logs: pathlib.Path, owner: str) -> pathlib.Path:
    return logs / f"llama-{owner}.pid"


def stop_recorded(
    logs: pathlib.Path, stopper: LlamaStopper, owners: Iterable[str], folders: Sequence[pathlib.Path]
) -> int:
    """Stop the recorded server of each owner, if it is still running, and forget the record. Returns how many."""
    stopped = 0
    for owner in owners:
        record = _record(logs, owner)
        try:
            pid = int(record.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            continue
        if stopper.stop_llama(pid, folders):
            stopped += 1
        record.unlink(missing_ok=True)
    return stopped


def stop_for_service(logs: pathlib.Path, stopper: LlamaStopper, service: str, folders: Sequence[pathlib.Path]) -> int:
    """Before a service starts: stop the server its previous run may have left behind."""
    owner = OWNERS.get(service)
    return stop_recorded(logs, stopper, [owner], folders) if owner else 0


def stop_all(logs: pathlib.Path, stopper: LlamaStopper, install_folders: Sequence[pathlib.Path]) -> int:
    """After everything is stopped: stop every recorded server, then any other server run from Thursday's own
    llama.cpp folders. Returns how many were stopped."""
    stopped = stop_recorded(logs, stopper, OWNERS.values(), install_folders)
    for pid in stopper.llama_under(install_folders):
        if stopper.stop_llama(pid, install_folders):
            stopped += 1
    return stopped
