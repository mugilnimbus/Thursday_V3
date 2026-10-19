import json
import sqlite3
from pathlib import Path

import anyio
import httpx
import pytest
from pydantic import SecretStr
from thursday_gateway.application.backup import BackupService, BackupSettings
from thursday_gateway.domain.model import InvalidInput
from thursday_gateway.infrastructure.backup_client import ServiceBackups
from thursday_gateway.infrastructure.store import Store


def service(tmp_path: Path, keep: int = 2) -> tuple[BackupService, Path]:
    store = Store(tmp_path / "gateway.sqlite")
    with store.tx() as db:
        db.execute("insert into notifications (kind, title, body, created_at) values ('x', 't', 'b', 'now')")

    def agents(request: httpx.Request) -> httpx.Response:
        if request.url.host == "main":
            assert request.headers["authorization"] == "Bearer tok"
            return httpx.Response(200, json={"service": "main_agent", "files": {"main_agent.sqlite": 10}})
        raise httpx.ConnectError("down")

    folder = tmp_path / "backups"
    svc = BackupService(
        store,
        [tmp_path / "gateway.sqlite"],
        ServiceBackups(
            {"main_agent": "http://main", "voice_agent": "http://voice"},
            SecretStr("tok"),
            httpx.AsyncClient(transport=httpx.MockTransport(agents)),
        ),
        BackupSettings(folder=str(folder), keep_copies=keep),
    )
    return svc, folder


def test_backup_copies_own_data_records_partial_runs_and_prunes(tmp_path: Path) -> None:
    svc, folder = service(tmp_path)
    first = anyio.run(svc.run)
    assert first["complete"] is False and first["services"] == {
        "gateway": True,
        "main_agent": True,
        "voice_agent": False,
    }
    copy = Path(first["folder"]) / "gateway" / "gateway.sqlite"
    db = sqlite3.connect(copy)
    try:
        assert db.execute("select count(*) from notifications").fetchone()[0] == 1
    finally:
        db.close()
    manifest = json.loads((Path(first["folder"]) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["services"]["voice_agent"] == {"ok": False, "error": "ConnectError"}
    assert not any(p.name == ".env" for p in Path(first["folder"]).rglob("*"))
    for _ in range(2):
        import time

        time.sleep(1.1)
        anyio.run(svc.run)
    assert len([p for p in folder.iterdir() if p.is_dir()]) == 2
    assert svc.last_run() is not None


def test_backup_folder_must_be_absolute_and_chosen(tmp_path: Path) -> None:
    svc, _ = service(tmp_path)
    with pytest.raises(InvalidInput):
        svc.save_settings(BackupSettings(folder="relative/path"))
    svc.save_settings(BackupSettings(folder=""))
    with pytest.raises(InvalidInput):
        anyio.run(svc.run)


def complete_service(tmp_path: Path, keep: int) -> tuple[BackupService, Path, dict[str, bool]]:
    """A backup whose one other service can be switched off."""
    store = Store(tmp_path / "gateway.sqlite")
    up = {"main": True}

    def agents(request: httpx.Request) -> httpx.Response:
        if not up["main"]:
            raise httpx.ConnectError("down")
        return httpx.Response(200, json={"service": "main_agent", "files": {"main_agent.sqlite": 10}})

    folder = tmp_path / "backups"
    svc = BackupService(
        store,
        [tmp_path / "gateway.sqlite"],
        ServiceBackups(
            {"main_agent": "http://main"}, SecretStr("tok"), httpx.AsyncClient(transport=httpx.MockTransport(agents))
        ),
        BackupSettings(folder=str(folder), keep_copies=keep),
    )
    return svc, folder, up


def test_partial_backups_never_remove_the_last_complete_one(tmp_path: Path) -> None:
    svc, folder, up = complete_service(tmp_path, keep=1)
    good = anyio.run(svc.run)
    assert good["complete"] is True
    up["main"] = False
    for _ in range(3):
        assert anyio.run(svc.run)["complete"] is False
    left = sorted(p.name for p in folder.iterdir())
    assert Path(good["folder"]).name in left, "the copy that can be restored is still there"
    assert len(left) == 2, "beside it, only the newest run is kept"
    up["main"] = True
    newer = anyio.run(svc.run)
    assert [p.name for p in folder.iterdir()] == [Path(newer["folder"]).name], "a newer complete copy replaces it"


def test_two_backups_in_the_same_second_get_folders_of_their_own(tmp_path: Path) -> None:
    svc, folder, _ = complete_service(tmp_path, keep=5)
    runs = [anyio.run(svc.run) for _ in range(3)]
    names = [Path(r["folder"]).name for r in runs]
    assert len(set(names)) == 3 and names == sorted(names), "each run has its own folder, in order"
    assert all((folder / n / "manifest.json").exists() for n in names)
