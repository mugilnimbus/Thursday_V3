import os
import pathlib
import subprocess
import sys

import pytest
from thursday_tool_server.domain.workspace import SandboxViolation, Workspace


def refused(ws: Workspace, path: str, **kwargs: bool) -> str:
    with pytest.raises(SandboxViolation) as info:
        ws.resolve(path, **kwargs)
    return info.value.reason


def test_relative_paths_resolve_inside(layout) -> None:
    ws = Workspace(layout["ws"])
    assert ws.resolve("notes.txt") == ws.root / "notes.txt"
    assert ws.resolve("sub/../notes.txt") == ws.root / "notes.txt"
    assert ws.resolve("new/deeper/file.txt") == ws.root / "new" / "deeper" / "file.txt"


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("../outside/secret.txt", "outside_workspace"),
        ("sub/../../outside/secret.txt", "outside_workspace"),
        ("..", "outside_workspace"),
        ("\\\\server\\share\\x", "unc_or_device_path"),
        ("\\\\?\\C:\\Windows", "unc_or_device_path"),
        ("\\\\.\\PhysicalDrive0", "unc_or_device_path"),
        ("//server/share", "unc_or_device_path"),
        ("notes.txt:hidden", "alternate_data_stream"),
        ("NUL", "reserved_device_name"),
        ("sub/con.txt", "reserved_device_name"),
        ("COM1", "reserved_device_name"),
        ("notes.txt.", "trailing_dot_or_space"),
        ("notes.txt ", "trailing_dot_or_space"),
        ("", "invalid"),
        ("a\x00b", "invalid"),
    ],
)
def test_escape_attempts_are_refused(layout, path: str, reason: str) -> None:
    assert refused(Workspace(layout["ws"]), path) == reason


def test_absolute_path_outside_and_other_drive_refused(layout) -> None:
    ws = Workspace(layout["ws"])
    assert refused(ws, str(layout["outside"] / "secret.txt")) == "outside_workspace"
    if sys.platform == "win32":
        other = "Z:\\x" if not ws.root.drive.upper().startswith("Z") else "Y:\\x"
        assert refused(ws, other) == "outside_workspace"
        assert refused(ws, "C:relative") == "drive_relative_path"
        assert refused(ws, "\\Windows\\win.ini") == "outside_workspace"


def test_absolute_path_inside_with_different_case_is_allowed(layout) -> None:
    ws = Workspace(layout["ws"])
    shouted = str(ws.root / "notes.txt").upper() if sys.platform == "win32" else str(ws.root / "notes.txt")
    assert ws.resolve(shouted).name.lower() == "notes.txt"


def test_prefix_sibling_is_not_inside(tmp_path: pathlib.Path) -> None:
    (tmp_path / "ws").mkdir()
    (tmp_path / "ws-evil").mkdir()
    assert refused(Workspace(tmp_path / "ws"), str(tmp_path / "ws-evil" / "x")) == "outside_workspace"


def test_junction_to_outside_is_refused(layout, junction) -> None:
    junction(layout["ws"] / "escape", layout["outside"])
    ws = Workspace(layout["ws"])
    assert refused(ws, "escape/secret.txt") == "outside_workspace"
    assert refused(ws, "escape/new-file.txt") == "outside_workspace"
    assert refused(ws, "escape") == "outside_workspace"


def test_junction_itself_can_be_addressed_without_following(layout, junction) -> None:
    junction(layout["ws"] / "escape", layout["outside"])
    ws = Workspace(layout["ws"])
    assert ws.resolve("escape", follow_final_link=False) == ws.root / "escape"


def test_symlink_to_outside_is_refused(layout) -> None:
    link = layout["ws"] / "link.txt"
    try:
        os.symlink(layout["outside"] / "secret.txt", link)
    except OSError:
        pytest.skip("creating symlinks needs Developer Mode or admin rights here")
    assert refused(Workspace(layout["ws"]), "link.txt") == "outside_workspace"


def test_short_8_3_name_resolves_to_the_real_inside_path(layout) -> None:
    if sys.platform != "win32":
        pytest.skip("8.3 names are Windows-only")
    long_dir = layout["ws"] / "averylongfoldername"
    long_dir.mkdir()
    out = subprocess.run(
        ["cmd", "/c", "for", "%I", "in", f"({long_dir})", "do", "@echo", "%~sI"], capture_output=True, text=True
    ).stdout.strip()
    short = pathlib.Path(out).name
    if not short or short.lower() == long_dir.name:
        pytest.skip("8.3 name generation is disabled on this volume")
    assert Workspace(layout["ws"]).resolve(short).name.lower() == "averylongfoldername"


def test_root_is_refused_when_not_allowed(layout) -> None:
    ws = Workspace(layout["ws"])
    assert refused(ws, ".", allow_root=False) == "workspace_root"
    assert refused(ws, str(ws.root), allow_root=False) == "workspace_root"
