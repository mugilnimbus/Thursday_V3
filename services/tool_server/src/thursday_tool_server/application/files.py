"""File tools. Every path goes through the workspace sandbox before any I/O."""

import os
import pathlib
import shutil

from thursday_tool_server.domain.patching import PatchError, apply_unified_diff
from thursday_tool_server.domain.workspace import Workspace

MAX_WRITE_CHARS = 5_000_000
MAX_LIST_ENTRIES = 1000
BINARY_SNIFF_BYTES = 8192


class ToolFailure(Exception):
    """An expected failure reported to the model as a tool error so it can correct itself."""


class FileTools:
    def __init__(self, workspace: Workspace, output_limit: int) -> None:
        self._ws = workspace
        self._limit = output_limit

    def read(self, path: str, offset: int = 1, limit: int = 2000) -> str:
        target = self._ws.resolve(path)
        if not target.is_file():
            raise ToolFailure(f"not a file: {path}")
        with target.open("rb") as handle:
            if b"\x00" in handle.read(BINARY_SNIFF_BYTES):
                raise ToolFailure(f"binary file, not shown: {path}")
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(offset, 1)
        chosen = lines[start - 1 : start - 1 + max(limit, 1)]
        body = "\n".join(f"{number:>6}\t{text}" for number, text in enumerate(chosen, start=start))
        note = f"\n[lines {start}-{start + len(chosen) - 1} of {len(lines)}]" if len(chosen) < len(lines) else ""
        return self._cap(body + note)

    def list(self, path: str = ".") -> str:
        target = self._ws.resolve(path)
        if not target.is_dir():
            raise ToolFailure(f"not a folder: {path}")
        entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        shown = [f"{p.name}/" if p.is_dir() else p.name for p in entries[:MAX_LIST_ENTRIES]]
        if len(entries) > MAX_LIST_ENTRIES:
            shown.append(f"[{len(entries) - MAX_LIST_ENTRIES} more not shown]")
        return self._cap("\n".join(shown) or "[empty folder]")

    def write(self, path: str, content: str) -> str:
        if len(content) > MAX_WRITE_CHARS:
            raise ToolFailure(f"content too large ({len(content)} characters, limit {MAX_WRITE_CHARS})")
        target = self._ws.resolve(path, allow_root=False)
        if target.is_dir():
            raise ToolFailure(f"is a folder: {path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        with target.open("w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        return f"{'overwrote' if existed else 'created'} {self._ws.relative(target)} ({len(content)} characters)"

    def edit(self, path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
        if not old_string:
            raise ToolFailure("old_string must not be empty")
        target, text = self._read_text_for_change(path)
        count = text.count(old_string)
        if count == 0:
            raise ToolFailure("old_string not found; read the file and copy the exact text")
        if count > 1 and not replace_all:
            raise ToolFailure(
                f"old_string found {count} times; add surrounding text to make it unique or set replace_all"
            )
        updated = text.replace(old_string, new_string) if replace_all else text.replace(old_string, new_string, 1)
        self._write_text(target, updated)
        return f"edited {self._ws.relative(target)} ({count if replace_all else 1} replacement(s))"

    def patch(self, path: str, diff: str) -> str:
        target, text = self._read_text_for_change(path, must_exist=False)
        try:
            updated = apply_unified_diff(text, diff)
        except PatchError as exc:
            raise ToolFailure(str(exc)) from exc
        target.parent.mkdir(parents=True, exist_ok=True)
        self._write_text(target, updated)
        return f"patched {self._ws.relative(target)}"

    def delete(self, path: str, recursive: bool = False) -> str:
        target = self._ws.resolve(path, allow_root=False, follow_final_link=False)
        shown = self._ws.relative(target)
        if os.path.islink(target) or _is_junction(target):
            _remove_link(target)
            return f"removed link {shown} (its target was not touched)"
        if target.is_file():
            target.unlink()
            return f"deleted file {shown}"
        if target.is_dir():
            if any(target.iterdir()) and not recursive:
                raise ToolFailure(f"folder is not empty: {path}; set recursive to delete its contents")
            shutil.rmtree(target) if recursive else target.rmdir()
            return f"deleted folder {shown}"
        raise ToolFailure(f"not found: {path}")

    def _read_text_for_change(self, path: str, must_exist: bool = True) -> tuple[pathlib.Path, str]:
        target = self._ws.resolve(path, allow_root=False)
        if not target.exists():
            if must_exist:
                raise ToolFailure(f"not found: {path}")
            return target, ""
        if not target.is_file():
            raise ToolFailure(f"not a file: {path}")
        try:
            with target.open("r", encoding="utf-8", newline="") as handle:
                return target, handle.read()
        except UnicodeDecodeError as exc:
            raise ToolFailure(f"not UTF-8 text, cannot edit: {path}") from exc

    @staticmethod
    def _write_text(target: pathlib.Path, text: str) -> None:
        with target.open("w", encoding="utf-8", newline="") as handle:
            handle.write(text)

    def _cap(self, text: str) -> str:
        if len(text) <= self._limit:
            return text
        return text[: self._limit] + f"\n[output truncated at {self._limit} characters]"


def _is_junction(path: pathlib.Path) -> bool:
    return hasattr(os.path, "isjunction") and os.path.isjunction(path)


def _remove_link(path: pathlib.Path) -> None:
    """Remove a symlink or junction without following it."""
    if _is_junction(path) or (os.path.islink(path) and os.path.isdir(path)):
        os.rmdir(path)
    else:
        os.unlink(path)
