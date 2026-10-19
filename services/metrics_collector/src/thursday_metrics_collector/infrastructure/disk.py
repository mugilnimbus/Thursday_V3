"""How much disk Thursday's stored data uses: each service's database files, and the log files.

Only sizes are read, never contents. Program files kept in the data folder (the llama.cpp build, the speech
models) are not data that grows with use, so they are not counted.
"""

from pathlib import Path

from thursday_contracts.metrics import StorageSample

LOGS = "logs"


def _size(paths: list[Path]) -> int:
    total = 0
    for path in paths:
        try:
            total += path.stat().st_size
        except OSError:
            continue  # removed between listing and reading
    return total


class DataFolders:
    def __init__(self, root: Path) -> None:
        self._root = root

    def sizes(self) -> list[StorageSample]:
        """One entry per service that has database files, largest first, then the logs."""
        services = []
        folder = self._root / "services"
        for service in sorted(folder.iterdir()) if folder.is_dir() else []:
            used = _size([p for p in service.glob("*.sqlite*") if p.is_file()]) if service.is_dir() else 0
            if used:
                services.append(StorageSample(name=service.name, bytes=used))
        services.sort(key=lambda sample: -sample.bytes)
        logs = self._root / LOGS
        log_bytes = _size([p for p in logs.iterdir() if p.is_file()]) if logs.is_dir() else 0
        return [*services, *([StorageSample(name=LOGS, bytes=log_bytes)] if log_bytes else [])]
