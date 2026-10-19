from pathlib import Path

import pytest
from thursday_gateway.application.files import ProjectFiles, is_hidden, list_folders, model_folders
from thursday_gateway.application.projects import NotFound
from thursday_gateway.domain.model import InvalidInput


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "logs").mkdir(parents=True)
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / "README.md").write_text("# Demo", encoding="utf-8")
    (root / "logs" / "app.log").write_text("line", encoding="utf-8")
    (root / "node_modules" / "pkg" / "app.js").write_text("x", encoding="utf-8")
    (root / "image.bin").write_bytes(bytes([0, 1, 2]))
    (tmp_path / "secret.txt").write_text("outside", encoding="utf-8")
    return root


def test_lists_folders_first_and_previews_text(project: Path) -> None:
    files = ProjectFiles(str(project))
    listed = [(e.name, e.is_dir) for e in files.entries()]
    assert listed == [("logs", True), ("node_modules", True), ("image.bin", False), ("README.md", False)]
    assert [e.path for e in files.entries("logs")] == ["logs/app.log"]
    preview = files.preview("README.md")
    assert preview["text"] == "# Demo" and preview["binary"] is False
    assert files.preview("image.bin")["binary"] is True


def test_search_matches_names_and_skips_dependency_folders(project: Path) -> None:
    assert [e.path for e in ProjectFiles(str(project)).search("APP")] == ["logs/app.log"]
    with pytest.raises(InvalidInput):
        ProjectFiles(str(project)).search("a")


@pytest.mark.parametrize("path", ["../secret.txt", "logs/../../secret.txt", "C:/Windows/win.ini", "/etc/passwd"])
def test_nothing_outside_the_project_can_be_read(project: Path, path: str) -> None:
    files = ProjectFiles(str(project))
    with pytest.raises((InvalidInput, NotFound)):
        files.preview(path)
    with pytest.raises((InvalidInput, NotFound)):
        files.entries(path)


def test_folder_picker_lists_only_folders(project: Path) -> None:
    listing = list_folders(str(project))
    assert [f["name"] for f in listing["folders"]] == ["logs", "node_modules"]  # type: ignore[index]
    assert listing["parent"] == str(project.parent)
    assert list_folders("")["folders"], "an empty path lists the drives"
    with pytest.raises(InvalidInput):
        list_folders("relative/path")


def test_a_dot_folder_is_listed_on_windows_and_hidden_elsewhere(tmp_path: Path) -> None:
    import os
    import sys

    (tmp_path / ".lmstudio" / "models").mkdir(parents=True)
    (tmp_path / "Documents").mkdir()
    with os.scandir(tmp_path) as scan:
        items = {item.name: item for item in scan}
    assert not is_hidden(items[".lmstudio"], windows=True), "File Explorer shows it, so the folder picker does too"
    assert is_hidden(items[".lmstudio"], windows=False) and not is_hidden(items["Documents"], windows=False)
    if sys.platform == "win32":
        import subprocess

        (tmp_path / "Secret").mkdir()
        subprocess.run(["attrib", "+h", str(tmp_path / "Secret")], check=True)
        names = [f["name"] for f in list_folders(str(tmp_path))["folders"]]  # type: ignore[index]
        assert names == [".lmstudio", "Documents"], "what Windows itself hides stays out of the list"
        assert list_folders(str(tmp_path / "Secret"))["path"] == str(tmp_path / "Secret"), "a typed path still opens"


def test_the_place_lm_studio_keeps_its_models_is_offered_only_when_it_exists(tmp_path: Path) -> None:
    assert model_folders(tmp_path) == []
    models = tmp_path / ".lmstudio" / "models"
    models.mkdir(parents=True)
    assert model_folders(tmp_path) == [{"name": "LM Studio's models", "path": str(models)}]
    assert "model_folders" in list_folders("") and "model_folders" in list_folders(str(tmp_path))
