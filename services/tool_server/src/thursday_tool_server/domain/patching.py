"""Apply a unified diff to one file's text.

Each hunk's old block (context and removed lines) must be found exactly in the current
text. The search starts at the hunk's stated line and widens outward, so a file that
shifted a little still patches, and the nearest match wins. Hunks apply in order and
may not overlap. Line endings and the final newline of the original are kept.
"""

import re
from dataclasses import dataclass

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class PatchError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Hunk:
    old_start: int
    old: tuple[str, ...]
    new: tuple[str, ...]


def parse_unified_diff(diff: str) -> list[Hunk]:
    hunks: list[Hunk] = []
    old: list[str] = []
    new: list[str] = []
    start: int | None = None

    def flush() -> None:
        if start is not None:
            hunks.append(Hunk(start, tuple(old), tuple(new)))

    for raw in diff.splitlines():
        if raw.startswith(("---", "+++", "diff ", "index ")) and start is None:
            continue
        match = _HUNK.match(raw)
        if match:
            flush()
            start, old, new = int(match.group(1)), [], []
            continue
        if start is None:
            continue
        if raw.startswith("\\"):  # "\ No newline at end of file"
            continue
        tag, text = (raw[:1], raw[1:]) if raw else (" ", "")
        if tag == " ":
            old.append(text)
            new.append(text)
        elif tag == "-":
            old.append(text)
        elif tag == "+":
            new.append(text)
        else:
            raise PatchError(f"unexpected line in hunk: {raw[:80]!r}")
    flush()
    if not hunks:
        raise PatchError("no hunks found; expected a unified diff with @@ headers")
    return hunks


def apply_unified_diff(original: str, diff: str) -> str:
    newline = "\r\n" if "\r\n" in original else "\n"
    had_final_newline = original.endswith(("\n", "\r\n")) or original == ""
    lines = original.splitlines()
    cursor = 0
    offset = 0
    for number, hunk in enumerate(parse_unified_diff(diff), start=1):
        expected = max(hunk.old_start - 1 + offset, cursor)
        at = _find_block(lines, hunk.old, expected, cursor)
        if at is None:
            raise PatchError(f"hunk {number} does not match the file (expected near line {hunk.old_start})")
        lines[at : at + len(hunk.old)] = hunk.new
        cursor = at + len(hunk.new)
        offset += len(hunk.new) - len(hunk.old)
    text = newline.join(lines)
    return text + newline if had_final_newline and lines else text


def _find_block(lines: list[str], block: tuple[str, ...], expected: int, lower_bound: int) -> int | None:
    """Nearest index >= lower_bound where `block` matches, searching outward from `expected`."""
    size = len(block)
    last_start = len(lines) - size
    if size == 0:
        return min(max(expected, lower_bound), len(lines))
    for distance in range(max(last_start, 0) + 1):
        for candidate in (expected - distance, expected + distance):
            if lower_bound <= candidate <= last_start and tuple(lines[candidate : candidate + size]) == block:
                return candidate
        if expected - distance < lower_bound and expected + distance > last_start:
            break
    return None
