"""Fill the graphics cards in a chosen order: the model goes on the first card, and only what does not fit there
goes on the next. (llama.cpp by itself spreads a model over all the cards in proportion to their free memory.)

The numbers come from llama.cpp itself, without loading the model: `llama-server --list-devices` says how much
memory each card has free, and `llama-fit-params` says how much the model would use. This module only reads what
those two print and works out which cards to use and each one's share; the provider runs the tools.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

MARGIN_MB = 1024  # memory left free on every card, the same margin llama.cpp's own fitting keeps
HEADROOM = 1.03  # two cards use a little more than one (each has its own work buffers)
SHIFT = 0.06  # how much of the model moves to the next card when the first turns out too full

_DEVICE = re.compile(
    r"^\s*(?P<name>[A-Za-z]+\d+):\s*(?P<label>.+?)\s*\((?P<total>\d+) MiB, (?P<free>\d+) MiB free\)\s*$"
)
_PROJECTED = re.compile(r"projected to use (\d+) MiB of device memory vs\. (\d+) MiB of free device memory")
_FITS = "no changes needed"  # said for one card ("will leave ... no changes needed") and for several
DOES_NOT_FIT = "cannot meet free memory target"


@dataclass(frozen=True, slots=True)
class Device:
    name: str  # what llama.cpp calls it: CUDA0, Vulkan1, ...
    label: str  # the card's own name
    total_mb: int
    free_mb: int

    @property
    def index(self) -> int:
        return int(re.sub(r"\D", "", self.name) or 0)


@dataclass(frozen=True, slots=True)
class Fit:
    need_mb: int | None  # memory the model would use on the cards, when the tool said
    fits: bool


def parse_devices(text: str) -> list[Device]:
    """The cards in the output of `llama-server --list-devices`."""
    found = []
    for line in text.splitlines():
        match = _DEVICE.match(line)
        if match:
            found.append(Device(match["name"], match["label"], int(match["total"]), int(match["free"])))
    return found


def parse_fit(text: str) -> Fit:
    """What `llama-fit-params -lv 4` printed: how much the model needs, and whether every card keeps its margin."""
    projected = _PROJECTED.search(text)
    return Fit(int(projected[1]) if projected else None, _FITS in text and DOES_NOT_FIT not in text)


def in_order(devices: Sequence[Device], first: Sequence[int]) -> list[Device]:
    """The cards in fill order: the chosen ones first, in the order given, then the rest by number."""
    by_index = {device.index: device for device in devices}
    chosen = [by_index[i] for i in dict.fromkeys(first) if i in by_index]
    return chosen + [device for device in devices if device not in chosen]


def fill(need_mb: float, devices: Sequence[Device], margins: Sequence[int]) -> list[int] | None:
    """How much of the model each card takes, filling them in order. Only the cards that are needed are listed.
    None when the model does not fit on all the cards together (then llama.cpp decides, and part runs on the CPU)."""
    shares: list[int] = []
    left = need_mb
    for device, margin in zip(devices, margins, strict=True):
        room = device.free_mb - margin
        if room <= 0:
            return None
        take = min(left, room)
        shares.append(round(take))
        left -= take
        if left <= 0:
            return shares
    return None


def shifted(shares: Sequence[int]) -> list[int]:
    """Move a little of the model from each card to the next one, for when the plan was a little too full."""
    moved = list(shares)
    step = round(sum(shares) * SHIFT)
    for i in range(len(moved) - 1):
        give = min(step, moved[i] - 1)
        moved[i] -= give
        moved[i + 1] += give
    return moved
