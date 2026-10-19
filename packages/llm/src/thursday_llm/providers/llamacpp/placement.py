"""Asking llama.cpp's own tools which graphics cards there are and where a model fits, without loading it.

`gpu_plan` reads what the tools print and does the arithmetic; this module runs them and turns the result into
arguments for `llama-server`.
"""

import asyncio
import logging
import os
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from thursday_llm import gpu_plan
from thursday_llm.config import LoadParameters
from thursday_llm.providers.llamacpp.arguments import model_arguments

log = logging.getLogger(__name__)
TOOL_TIMEOUT_SECONDS = 90.0
PLAN_ATTEMPTS = 4

RunTool = Callable[[list[str], str | None], str]
"""Runs one of llama.cpp's tools and returns what it printed (see `run_tool`)."""


@dataclass(frozen=True, slots=True)
class Plan:
    arguments: list[str] = field(default_factory=list)  # empty: llama.cpp spreads the model as it sees fit
    words: str = ""  # the placement in words, for the log and Settings


def environment(gpu: int | None) -> dict[str, str]:
    """Cards are numbered the way the system numbers them (as Monitor and nvidia-smi do), for every program
    run here; with one card chosen, only that card is visible."""
    env = dict(os.environ)
    env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    if gpu is not None:
        env["CUDA_VISIBLE_DEVICES"] = str(gpu)
    return env


def run_tool(command: list[str], env: dict[str, str], stop_at: str | None = None) -> str:
    """Run one of llama.cpp's own tools and return what it printed. With `stop_at`, the tool is stopped as soon
    as a line holds that text (its answer is known, and the rest of its work is not needed)."""
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0  # type: ignore[attr-defined]
    process = subprocess.Popen(  # noqa: S603 - a program from the llama.cpp folder, fixed arguments, no shell
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env=env,
        creationflags=flags,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    lines: list[str] = []
    deadline = time.monotonic() + TOOL_TIMEOUT_SECONDS
    try:
        assert process.stdout is not None
        for line in process.stdout:
            lines.append(line)
            if (stop_at and stop_at in line) or time.monotonic() > deadline:
                break
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(10)
    return "".join(lines)


def fitter_beside(exe: Path) -> Path | None:
    """`llama-fit-params`, which ships next to `llama-server` and says how much memory a load would use."""
    fitter = exe.with_name("llama-fit-params" + exe.suffix)
    return fitter if fitter.is_file() else None


async def cards(exe: Path, run: RunTool) -> list[gpu_plan.Device]:
    """The graphics cards llama.cpp sees, with their free memory now."""
    return gpu_plan.parse_devices(await asyncio.to_thread(run, [str(exe), "--list-devices"], None))


async def fill_in_order(
    fitter: Path,
    model: Path,
    load: LoadParameters,
    devices: Sequence[gpu_plan.Device],
    projector_mb: int,
    run: RunTool,
) -> Plan:
    """Put the model on the first card of the chosen order, and only what does not fit there on the next.
    An empty plan when that cannot be worked out or would not fit."""
    first = [int(n) for n in (load.gpu_priority or "").split(",") if n.strip().isdigit()]
    ordered = gpu_plan.in_order(devices, first)
    if len(ordered) < 2:
        return Plan()
    margins = [gpu_plan.MARGIN_MB] * len(ordered)
    margins[0] += projector_mb  # the projector goes on the first card and the fitting tool does not count it
    base = [str(fitter), *model_arguments(model, load), "-lv", "4"]

    async def check(extra: list[str]) -> gpu_plan.Fit:
        return gpu_plan.parse_fit(await asyncio.to_thread(run, [*base, *extra], gpu_plan.DOES_NOT_FIT))

    alone = ["--device", ordered[0].name, "--fit-target", str(margins[0])]
    one = await check(alone)
    if one.fits:
        return Plan(alone, f"all on card {ordered[0].index}")
    if one.need_mb is None:
        return Plan()
    shares = gpu_plan.fill(one.need_mb * gpu_plan.HEADROOM, ordered, margins)
    for _ in range(PLAN_ATTEMPTS):
        if shares is None:
            break
        used = ordered[: len(shares)]
        extra = [
            "--device",
            ",".join(d.name for d in used),
            "--tensor-split",
            ",".join(str(s) for s in shares),
            "--fit-target",
            ",".join(str(m) for m in margins[: len(used)]),
        ]
        if (await check(extra)).fits:
            words = ", ".join(f"card {d.index}: {s / 1024:.1f} GB" for d, s in zip(used, shares, strict=True))
            return Plan(extra, words)
        shares = gpu_plan.shifted(shares)
    log.warning("%s does not fit on the cards in the chosen order; llama.cpp spreads it instead", model.name)
    return Plan()
