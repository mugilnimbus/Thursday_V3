"""Read-only views of the PC's folders for the clients.

Two uses, both read-only:
- picking a folder (for a new project, or the models folder of the built-in llama.cpp): list the sub-folders of a
  folder (names only), starting at the drives, with shortcuts to where LM Studio keeps its models;
- looking inside a project: list a folder, search file names, and preview a text file.

Project views never leave the project folder: every path is resolved (following links) and must still
be inside the folder. Nothing here writes, and file contents are capped and returned as text only.
"""

import os
import stat
import string
import sys
from dataclasses import dataclass
from pathlib import Path

from thursday_gateway.application.projects import NotFound
from thursday_gateway.domain.model import InvalidInput

MAX_ENTRIES = 500
MAX_RESULTS = 200
MAX_SCANNED = 20_000
MAX_PREVIEW_BYTES = 200_000
SKIPPED_DIRS = {".git", "node_modules", ".venv", "__pycache__", ".gradle", "build", "dist", ".idea"}


@dataclass(frozen=True, slots=True)
class Entry:
    name: str
    path: str  # relative to the project folder, with forward slashes
    is_dir: bool
    size: int | None

    def as_json(self) -> dict[str, object]:
        return {"name": self.name, "path": self.path, "is_dir": self.is_dir, "size": self.size}


def roots() -> list[str]:
    if sys.platform == "win32":
        return [f"{letter}:\\" for letter in string.ascii_uppercase if os.path.exists(f"{letter}:\\")]
    return ["/"]


def is_hidden(item: os.DirEntry[str], windows: bool = sys.platform == "win32") -> bool:
    """What the operating system itself hides. On Windows that is the hidden or system mark, not a leading dot:
    `.lmstudio` is an ordinary folder there, and File Explorer shows it. Elsewhere a leading dot hides."""
    if not windows:
        return item.name.startswith(".")
    marks = getattr(item.stat(follow_symlinks=False), "st_file_attributes", 0)
    return bool(marks & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM))


def model_folders(home: Path | None = None) -> list[dict[str, str]]:
    """Folders where another program on this PC keeps downloaded model files, offered as shortcuts when a models
    folder is being chosen. Only the ones that exist. LM Studio keeps them under a dot folder, which is hidden from
    folder lists on Linux and macOS, so a shortcut is the way in there."""
    home = home or Path.home()
    known = (
        ("LM Studio's models", home / ".lmstudio" / "models"),
        ("LM Studio's models (older location)", home / ".cache" / "lm-studio" / "models"),
    )
    return [{"name": name, "path": str(path)} for name, path in known if path.is_dir()]


def list_folders(path: str) -> dict[str, object]:
    """Sub-folders of an absolute folder, for choosing a folder on the PC. An empty path lists the drives.
    Folders the operating system hides are left out; a path typed by hand still opens them."""
    if not path.strip():
        return {
            "path": "",
            "parent": None,
            "folders": [{"name": r, "path": r} for r in roots()],
            "home": str(Path.home()),
            "model_folders": model_folders(),
        }
    folder = Path(path)
    if not folder.is_absolute():
        raise InvalidInput("the folder must be an absolute path")
    folder = folder.resolve()
    if not folder.is_dir():
        raise NotFound(str(folder))
    names: list[str] = []
    try:
        with os.scandir(folder) as scan:
            for item in scan:
                try:
                    if item.is_dir() and not item.name.startswith("$") and not is_hidden(item):
                        names.append(item.name)
                except OSError:
                    continue
    except PermissionError as exc:
        raise InvalidInput("this folder cannot be opened") from exc
    names.sort(key=str.lower)
    parent = "" if folder.parent == folder else str(folder.parent)
    return {
        "path": str(folder),
        "parent": parent,
        "folders": [{"name": n, "path": str(folder / n)} for n in names[:MAX_ENTRIES]],
        "home": str(Path.home()),
        "model_folders": model_folders(),
    }


class ProjectFiles:
    def __init__(self, folder: str) -> None:
        self._root = Path(folder).resolve()

    def _inside(self, relative: str) -> Path:
        if Path(relative).is_absolute() or ":" in relative:
            raise InvalidInput("the path must be relative to the project folder")
        target = (self._root / relative).resolve()
        if target != self._root and self._root not in target.parents:
            raise InvalidInput("the path is outside the project folder")
        return target

    def _entry(self, path: Path) -> Entry:
        is_dir = path.is_dir()
        size = None if is_dir else path.stat().st_size
        return Entry(path.name, path.relative_to(self._root).as_posix(), is_dir, size)

    def entries(self, relative: str = "") -> list[Entry]:
        folder = self._inside(relative)
        if not folder.is_dir():
            raise NotFound(relative or ".")
        entries: list[Entry] = []
        for child in folder.iterdir():
            try:
                if self._inside(child.relative_to(self._root).as_posix()) and child.exists():
                    entries.append(self._entry(child))
            except (OSError, InvalidInput):
                continue  # unreadable, or a link that points outside the project
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries[:MAX_ENTRIES]

    def search(self, query: str) -> list[Entry]:
        """Files and folders whose name contains the text (case-insensitive), skipping build and cache folders."""
        needle = query.strip().lower()
        if len(needle) < 2:
            raise InvalidInput("type at least 2 characters to search")
        found: list[Entry] = []
        scanned = 0
        for current, dirs, files in os.walk(self._root):
            dirs[:] = [d for d in dirs if d not in SKIPPED_DIRS]
            for name in [*dirs, *files]:
                scanned += 1
                if needle in name.lower():
                    try:
                        found.append(self._entry(Path(current) / name))
                    except OSError:
                        continue
                if len(found) >= MAX_RESULTS or scanned >= MAX_SCANNED:
                    return found
        return found

    def preview(self, relative: str) -> dict[str, object]:
        path = self._inside(relative)
        if not path.is_file():
            raise NotFound(relative)
        size = path.stat().st_size
        with path.open("rb") as handle:
            data = handle.read(MAX_PREVIEW_BYTES)
        if b"\x00" in data[:8000]:
            return {"path": relative, "size": size, "text": None, "truncated": False, "binary": True}
        return {
            "path": relative,
            "size": size,
            "text": data.decode("utf-8", errors="replace"),
            "truncated": size > MAX_PREVIEW_BYTES,
            "binary": False,
        }
