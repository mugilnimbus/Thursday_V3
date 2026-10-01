import pathlib
import subprocess
import sys

import pytest


@pytest.fixture
def layout(tmp_path: pathlib.Path) -> dict[str, pathlib.Path]:
    """A workspace folder and a sibling 'outside' folder holding a secret file."""
    ws = tmp_path / "workspace"
    outside = tmp_path / "outside"
    ws.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    (ws / "notes.txt").write_text("hello\n", encoding="utf-8")
    return {"ws": ws, "outside": outside}


def make_junction(link: pathlib.Path, target: pathlib.Path) -> None:
    """Directory junctions need no admin rights on Windows."""
    if sys.platform != "win32":
        pytest.skip("junctions are Windows-only")
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)


@pytest.fixture
def junction():
    return make_junction
