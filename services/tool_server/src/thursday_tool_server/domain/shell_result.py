"""Outcome of running a shell command."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ShellResult:
    exit_code: int | None
    output: str
    timed_out: bool
    truncated: bool
