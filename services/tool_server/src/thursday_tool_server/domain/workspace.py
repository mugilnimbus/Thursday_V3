"""The workspace sandbox: every path a tool touches must resolve inside the project folder.

Paths are checked twice. First as text (UNC and device paths, alternate data streams,
reserved device names, trailing dots or spaces, and `..` escapes are refused). Then the
deepest existing ancestor is resolved with `realpath`, which follows symlinks and
junctions and expands 8.3 short names, and the result must still be inside the root.
Nothing a model or prompt says can widen this.
"""

import ntpath
import os
import pathlib
import re

MAX_PATH_CHARS = 4096
_DRIVE = re.compile(r"^[A-Za-z]:")
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"COM{i}" for i in range(10)}
    | {f"LPT{i}" for i in range(10)}
    | {f"COM{c}" for c in "¹²³"}
    | {f"LPT{c}" for c in "¹²³"}
)


class SandboxViolation(Exception):
    """A path was refused. `reason` is a short, stable code safe to show the model."""

    def __init__(self, reason: str, path: str) -> None:
        super().__init__(f"path refused ({reason}): {path}")
        self.reason = reason
        self.path = path


class Workspace:
    def __init__(self, root: str | os.PathLike[str]) -> None:
        real = pathlib.Path(os.path.realpath(root))
        if not real.is_dir():
            raise ValueError(f"workspace root is not a folder: {root}")
        self._root = real
        self._root_key = os.path.normcase(str(real))

    @property
    def root(self) -> pathlib.Path:
        return self._root

    def resolve(self, user_path: str, *, allow_root: bool = True, follow_final_link: bool = True) -> pathlib.Path:
        """Return the real, absolute path for `user_path`, or raise `SandboxViolation`.

        With `follow_final_link=False` a final symlink or junction is returned as the link
        itself (its folder is still resolved for real), so deleting it never touches its target.
        """
        self._check_text(user_path)
        candidate = pathlib.Path(user_path)
        if not candidate.is_absolute():
            candidate = self._root / candidate
        normalized = pathlib.Path(os.path.normpath(candidate))
        self._check_inside(normalized, user_path, allow_root)
        if not follow_final_link and _is_link(normalized):
            real = self._real(normalized.parent) / normalized.name
        else:
            real = self._real(normalized)
        self._check_inside(real, user_path, allow_root)
        return real

    def relative(self, path: pathlib.Path) -> str:
        """Display form of a resolved path, relative to the root, with forward slashes."""
        rel = path.relative_to(self._root)
        return rel.as_posix() or "."

    def _check_text(self, user_path: str) -> None:
        if not user_path or len(user_path) > MAX_PATH_CHARS or "\x00" in user_path:
            raise SandboxViolation("invalid", user_path)
        if user_path.startswith(("\\\\", "//")):
            raise SandboxViolation("unc_or_device_path", user_path)
        rest = user_path[2:] if _DRIVE.match(user_path) else user_path
        if _DRIVE.match(user_path) and not rest.startswith(("\\", "/")):
            raise SandboxViolation("drive_relative_path", user_path)
        if ":" in rest:
            raise SandboxViolation("alternate_data_stream", user_path)
        for part in re.split(r"[\\/]+", rest):
            if part in ("", ".", ".."):
                continue
            if part.endswith((".", " ")):
                raise SandboxViolation("trailing_dot_or_space", user_path)
            if part.split(".")[0].rstrip(" ").upper() in _WINDOWS_RESERVED:
                raise SandboxViolation("reserved_device_name", user_path)

    def _check_inside(self, path: pathlib.Path, user_path: str, allow_root: bool) -> None:
        key = os.path.normcase(str(path))
        if key == self._root_key:
            if not allow_root:
                raise SandboxViolation("workspace_root", user_path)
            return
        if not key.startswith(self._root_key.rstrip(ntpath.sep + "/") + os.sep):
            raise SandboxViolation("outside_workspace", user_path)

    @staticmethod
    def _real(path: pathlib.Path) -> pathlib.Path:
        """Resolve the deepest existing ancestor for real, then re-attach the not-yet-existing tail."""
        existing = path
        tail: list[str] = []
        while not os.path.lexists(existing) and existing.parent != existing:
            tail.append(existing.name)
            existing = existing.parent
        real = pathlib.Path(os.path.realpath(existing))
        for name in reversed(tail):
            real = real / name
        return real


def _is_link(path: pathlib.Path) -> bool:
    return os.path.islink(path) or (hasattr(os.path, "isjunction") and os.path.isjunction(path))
