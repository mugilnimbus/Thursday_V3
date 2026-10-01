"""Per-service backup of its own SQLite files, requested by the gateway.

Uses SQLite's online backup API, so the copy is consistent while the service keeps running.
Secrets never live in these files (keys stay in `.env`, which is never backed up).
"""

import os
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from thursday_runtime.auth import ServiceTokenAuth


def backup_sqlite(source: Path, destination: Path) -> int:
    """Copy one database; returns the size of the copy in bytes."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(source)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return destination.stat().st_size


class BackupRequest(BaseModel):
    target_dir: str


def build_backup_router(service: str, files: list[Path], auth: ServiceTokenAuth) -> APIRouter:
    router = APIRouter(prefix="/v1", dependencies=[Depends(auth)])

    @router.post("/backup")
    async def backup(body: BackupRequest) -> dict[str, object]:
        if not os.path.isabs(body.target_dir):
            raise HTTPException(422, "target_dir must be absolute")
        target = Path(body.target_dir) / service
        written = {f.name: backup_sqlite(f, target / f.name) for f in files if f.exists()}
        return {"service": service, "files": written}

    return router
