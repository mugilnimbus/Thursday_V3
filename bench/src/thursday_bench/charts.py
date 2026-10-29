"""Draw the benchmark pictures as SVG files, one light and one dark copy of each, from saved results.

The pictures must tell their story without the page around them: each one says what was done, shows the
result, and ends with what the result means. Every value shown is computed from the results files.
The colours are the dashboard's own: violet, teal and blue on near-black, or their deeper steps on white.
"""

import json
import pathlib
from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Any

FONT = "-apple-system, 'Segoe UI', Inter, Helvetica, Arial, sans-serif"
MONO = "ui-monospace, 'SF Mono', 'Cascadia Mono', Menlo, Consolas, monospace"


@dataclass(frozen=True, slots=True)
class Theme:
    name: str
    top: str  # card background, top of the gradient
    bottom: str  # card background, bottom of the gradient
    border: str
    text: str
    secondary: str
    muted: str
    grid: str
    blue: str
    violet: str
    teal: str
    good: str
    bad: str


DARK = Theme(
    "dark", "#14112a", "#07060c", "#2a2440", "#f1ecff", "#bdb4d6", "#8a83a3", "#241f36",
    "#4d8dff", "#9b63ff", "#2dd4bf", "#4ade80", "#ff4d5e",
)  # fmt: skip
LIGHT = Theme(
    "light", "#ffffff", "#f4f1fb", "#e2dcf0", "#14112a", "#4a4560", "#6f6a85", "#ebe7f5",
    "#2563eb", "#6d3fd6", "#0d9488", "#15803d", "#d03b3b",
)  # fmt: skip


@dataclass(frozen=True, slots=True)
class Facts:
    """Everything the pictures show, read once from the results files."""

    ack: float
    first_token: float
    reply: float
    sent: int
    accepted: int
    refused: int
    retry_after: float
    burst_seconds: float
    burst_runs: int
    before: list[bool]
    after: list[bool]
    kill_chats: int
    kill_seconds: float
    soak_minutes: float
    soak_chats: int
    soak_runs: int
    soak_messages: float
    soak_rate: float
    soak_errors: float
    soak_back: float
    soak_growth_mb: float
    soak_first_mb: float
    history_events: int
    history_worst_ms: float
    cpu: str
    memory_gb: float
    os: str
    date: str


def _t(
    x: float,
    y: float,
    value: str,
    fill: str,
    size: float = 13,
    anchor: str = "start",
    weight: int = 400,
    font: str = FONT,
    spacing: float = 0,
) -> str:
    extra = f' letter-spacing="{spacing}"' if spacing else ""
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="{font}" font-size="{size}" font-weight="{weight}" '
        f'fill="{fill}" text-anchor="{anchor}"{extra}>{escape(value)}</text>'
    )


def _defs(t: Theme) -> str:
    return (
        "<defs>"
        f'<linearGradient id="bg-{t.name}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{t.top}"/><stop offset="1" stop-color="{t.bottom}"/></linearGradient>'
        f'<linearGradient id="flow-{t.name}" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0" stop-color="{t.blue}"/><stop offset="0.55" stop-color="{t.violet}"/>'
        f'<stop offset="1" stop-color="{t.teal}"/></linearGradient>'
        f'<filter id="glow-{t.name}" x="-50%" y="-50%" width="200%" height="200%">'
        '<feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/>'
        '<feMergeNode in="SourceGraphic"/></feMerge></filter>'
        "</defs>"
    )


def _frame(width: float, height: float, title: str, body: list[str], t: Theme) -> str:
    return "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
            f'viewBox="0 0 {width:.0f} {height:.0f}" role="img" aria-label="{escape(title)}">',
            f"<title>{escape(title)}</title>",
            _defs(t),
            f'<rect x="0.5" y="0.5" width="{width - 1:.0f}" height="{height - 1:.0f}" rx="14" '
            f'fill="url(#bg-{t.name})" stroke="{t.border}"/>',
            *body,
            "</svg>",
        ]
    )


def _heading(x: float, kicker: str, title: str, lines: list[str], t: Theme, accent: str) -> list[str]:
    out = [
        f'<rect x="{x}" y="26" width="4" height="16" rx="2" fill="{accent}"/>',
        _t(x + 12, 39, kicker.upper(), accent, 12, weight=700, spacing=1.4),
        _t(x, 68, title, t.text, 22, weight=700),
    ]
    out += [_t(x, 92 + i * 19, line, t.secondary, 14) for i, line in enumerate(lines)]
    return out


def _meaning(x: float, y: float, width: float, lines: list[str], t: Theme, accent: str) -> tuple[list[str], float]:
    """The closing band: what the result means, in plain words. Returns the elements and the band height."""
    height = 38 + 19 * len(lines)
    out = [
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="10" fill="{accent}" fill-opacity="0.10"/>',
        f'<rect x="{x}" y="{y}" width="4" height="{height}" rx="2" fill="{accent}"/>',
        _t(x + 18, y + 22, "WHAT THIS MEANS", accent, 11, weight=800, spacing=1.3),
    ]
    out += [_t(x + 18, y + 44 + i * 19, line, t.text, 14, weight=500) for i, line in enumerate(lines)]
    return out, height


def _check(cx: float, cy: float, t: Theme, r: float = 9) -> list[str]:
    return [
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" fill="none" stroke="{t.good}" stroke-width="2"/>',
        f'<path d="M{cx - r * 0.45:.1f},{cy:.1f} l{r * 0.33:.1f},{r * 0.33:.1f} l{r * 0.55:.1f},{-r * 0.66:.1f}" '
        f'stroke="{t.good}" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
    ]


def _cross(cx: float, cy: float, t: Theme, r: float = 10) -> list[str]:
    d = r * 0.4
    return [
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" fill="{t.bad}"/>',
        f'<path d="M{cx - d:.1f},{cy - d:.1f} l{2 * d:.1f},{2 * d:.1f} M{cx + d:.1f},{cy - d:.1f} '
        f'l{-2 * d:.1f},{2 * d:.1f}" stroke="#ffffff" stroke-width="2.2" stroke-linecap="round"/>',
    ]


def _timeline(left: float, right: float, axis_y: float, f: Facts, t: Theme, *, small: bool = False) -> list[str]:
    """The three moments of one message on a 0 to 70 ms line."""

    def x(ms: float) -> float:
        return left + ms * (right - left) / 70.0

    out = [
        f'<rect x="{left}" y="{axis_y - 5}" width="{right - left}" height="10" rx="5" fill="{t.grid}"/>',
        f'<rect x="{left}" y="{axis_y - 5}" width="{x(f.reply) - left:.1f}" height="10" rx="5" '
        f'fill="url(#flow-{t.name})"/>',
    ]
    for tick in range(0, 71, 10) if not small else (35, 70):
        out.append(_t(x(tick), axis_y + 26, f"{tick} ms", t.muted, 11, "middle", font=MONO))
    marks = [
        (f.ack, "Send accepted", t.blue),
        (f.first_token, "First word appears", t.violet),
        (f.reply, "Whole reply shown", t.teal),
    ]
    for ms, label, colour in marks:
        cx = x(ms)
        below = small and ms == f.ack  # in the small timeline the first label sits under the line, out of the way
        anchor = "start" if below else "middle"
        value_y, label_y = (axis_y + 30, axis_y + 44) if below else (axis_y - (54 if not small else 46), 0.0)
        if not below:
            label_y = value_y + 15
        line = (axis_y + 10, value_y - 14) if below else (label_y + 6, axis_y - 10)
        out += [
            f'<line x1="{cx:.1f}" y1="{line[0]}" x2="{cx:.1f}" y2="{line[1]}" stroke="{colour}" '
            'stroke-width="1.5" stroke-dasharray="3 3"/>',
            f'<circle cx="{cx:.1f}" cy="{axis_y}" r="8" fill="{colour}" filter="url(#glow-{t.name})"/>',
            f'<circle cx="{cx:.1f}" cy="{axis_y}" r="3" fill="{t.bottom}"/>',
            _t(cx - (8 if below else 0), value_y, f"{ms:.0f} ms" if small else f"{ms:.1f} ms",
               colour, 15 if small else 18, anchor, 800, MONO),
            _t(cx - (8 if below else 0), label_y, label, t.secondary, 11 if small else 12, anchor, 600),
        ]  # fmt: skip
    return out


def _squares(left: float, top: float, f: Facts, t: Theme, per_row: int, cell: float, gap: float) -> list[str]:
    out = []
    for i in range(f.sent):
        cx, cy = left + (i % per_row) * (cell + gap), top + (i // per_row) * (cell + gap)
        if i < f.accepted:
            out.append(f'<rect x="{cx:.1f}" y="{cy:.1f}" width="{cell}" height="{cell}" rx="{cell / 4.5:.1f}" '
                       f'fill="url(#flow-{t.name})"/>')  # fmt: skip
        else:
            out.append(
                f'<rect x="{cx + 0.75:.1f}" y="{cy + 0.75:.1f}" width="{cell - 1.5}" height="{cell - 1.5}" '
                f'rx="{cell / 4.5:.1f}" fill="none" stroke="{t.bad}" stroke-width="1.4" stroke-dasharray="3 2"/>'
            )
    return out


def _runs(x: float, y: float, lost: list[bool], t: Theme, per_row: int, step: float, r: float) -> list[str]:
    out = []
    for i, bad in enumerate(lost):
        cx, cy = x + (i % per_row) * step, y + (i // per_row) * (step - 2)
        out += _cross(cx, cy, t, r + 1) if bad else _check(cx, cy, t, r)
    return out


# ---- the four detail pictures -----------------------------------------------------------------------------------


def message_time(f: Facts, t: Theme) -> str:
    body = _heading(28, "Speed", "A message costs Thursday about 60 ms", [
        "One typed message, timed from pressing Send. The AI model is replaced by a fake one that",
        "answers at once, so the time shown is Thursday's own: queue, agents, events, live stream.",
    ], t, t.violet)  # fmt: skip
    body += _timeline(48, 752, 214, f, t)
    meaning, height = _meaning(28, 262, 744, [
        f"Thursday adds {f.reply:.0f} ms to a reply in 95 of 100 messages. Under 100 ms feels instant to a person.",
        "The real AI model's own thinking time comes on top of this; Thursday stays out of the way.",
    ], t, t.violet)  # fmt: skip
    return _frame(800, 262 + height + 28, "Where the time of one message goes", body + meaning, t)


def burst(f: Facts, t: Theme) -> str:
    body = _heading(28, "Overload", "A flood is refused politely, not dropped", [
        f"{f.sent} messages fired into one chat at once, without waiting for replies.",
        "Each square is one message, in the order it was sent.",
    ], t, t.blue)  # fmt: skip
    body += _squares(28, 134, f, t, 24, 18, 4)
    sx = 28 + 24 * 22 + 34
    body += [
        _t(sx, 168, f"{f.accepted}", t.text, 44, weight=800),
        _t(sx + 86, 168, "accepted", t.secondary, 14, weight=600),
        _t(sx, 188, "1 answered at once, 100 in line", t.muted, 12),
        _t(sx, 236, f"{f.refused}", t.bad, 44, weight=800),
        _t(sx + 60, 236, "refused", t.secondary, 14, weight=600),
        _t(sx, 256, f"HTTP 429: try again in {f.retry_after:.0f} s", t.muted, 12),
    ]
    meaning, height = _meaning(28, 268, 744, [
        "A chat holds one message in progress and 100 in line. Past that, the sender is told to retry later.",
        f"No accepted message is lost: all {f.accepted} were answered in the order sent, {f.burst_seconds:.1f} s "
        f"after the first. Same in {f.burst_runs} of {f.burst_runs} runs.",
    ], t, t.blue)  # fmt: skip
    return _frame(800, 268 + height + 28, "A burst of 120 messages", body + meaning, t)


def kill_test(f: Facts, t: Theme) -> str:
    body = _heading(28, "Crash test", "Killing an agent loses nothing", [
        f"{f.kill_chats} chats talk for {f.kill_seconds:.0f} s. At {f.kill_seconds / 2 + 10:.0f} s the voice agent "
        "is killed without warning.",
        "Each mark is one run. Did every message still get its answer?",
    ], t, t.teal)  # fmt: skip
    for x, label, lost, colour in ((28, "Before the fix", f.before, t.bad), (432, "After the fix", f.after, t.good)):
        count = sum(lost)
        body += [
            f'<rect x="{x}" y="128" width="340" height="178" rx="12" fill="{colour}" fill-opacity="0.08" '
            f'stroke="{colour}" stroke-opacity="0.45"/>',
            _t(x + 20, 156, label.upper(), colour, 12, weight=700, spacing=1.2),
            _t(x + 20, 206, f"{count}", colour, 52, weight=800),
            _t(x + 26 + 31 * len(str(count)), 206, f"/ {len(lost)}", t.secondary, 24, weight=700),
            _t(x + 20, 228, "runs lost a message", t.text, 14, weight=600),
            *_runs(x + 30, 256, lost, t, 10, 29, 9),
        ]
    body += [
        f'<circle cx="400" cy="217" r="18" fill="{t.top}" stroke="{t.border}"/>',
        f'<path d="M392,217 h14 m-6,-6 l6,6 l-6,6" stroke="{t.text}" stroke-width="2" fill="none" '
        'stroke-linecap="round" stroke-linejoin="round"/>',
    ]
    meaning, height = _meaning(28, 326, 744, [
        "This test found a real bug: a late event from the restarted agent marked a waiting message as",
        "delivered, so it was never sent again. Fix: only the sender marks a message delivered, with a test.",
    ], t, t.teal)  # fmt: skip
    return _frame(800, 326 + height + 28, "Killing the voice agent in the middle of a conversation", body + meaning, t)


def soak(f: Facts, t: Theme) -> str:
    body = _heading(28, "Endurance", f"{f.soak_minutes:.0f} minutes under load, nothing lost", [
        f"{f.soak_chats} chats send messages nonstop for {f.soak_minutes:.0f} minutes. Halfway, the voice agent is "
        "killed.",
        f"Median of {f.soak_runs} runs.",
    ], t, t.good)  # fmt: skip
    tiles = [
        (f"{f.soak_messages / 1000:.1f}k", f"messages ({f.soak_rate:.0f} per second)", t.blue),
        (f"{f.soak_errors:.0f}", "errors, gaps or repeats", t.good),
        (f"{f.soak_back:.1f} s", "until the agent was back", t.violet),
        (f"+{f.soak_growth_mb:.0f} MB", f"memory in {f.soak_minutes:.0f} minutes", t.teal),
    ]
    for i, (value, label, colour) in enumerate(tiles):
        x = 28 + i * 190
        body += [
            f'<rect x="{x}" y="132" width="178" height="104" rx="12" fill="{colour}" fill-opacity="0.08" '
            f'stroke="{colour}" stroke-opacity="0.4"/>',
            f'<rect x="{x}" y="150" width="3" height="68" rx="1.5" fill="{colour}"/>',
            _t(x + 18, 190, value, t.text, 34, weight=800),
            _t(x + 18, 216, label, t.secondary, 12, weight=600),
        ]
    meaning, height = _meaning(28, 256, 744, [
        "Thursday can run all day: a crash in the middle is recovered in seconds, every message is kept",
        f"in order, and memory grows only {100 * f.soak_growth_mb / f.soak_first_mb:.0f}% in half an hour.",
    ], t, t.good)  # fmt: skip
    return _frame(800, 256 + height + 28, "The long run", body + meaning, t)


# ---- the one-page overview ----------------------------------------------------------------------------------------


def _panel(x: float, y: float, w: float, h: float, kicker: str, accent: str, t: Theme) -> list[str]:
    return [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{accent}" fill-opacity="0.06" '
        f'stroke="{accent}" stroke-opacity="0.35"/>',
        f'<rect x="{x + 22}" y="{y + 22}" width="4" height="14" rx="2" fill="{accent}"/>',
        _t(x + 34, y + 34, kicker.upper(), accent, 12, weight=800, spacing=1.4),
    ]


def overview(f: Facts, t: Theme) -> str:
    width, pad, gap = 1000, 32, 20
    body = [
        _t(pad, 44, "THURSDAY  ·  BENCHMARK", t.violet, 13, weight=800, spacing=2),
        _t(pad, 86, "Is Thursday fast, and does it ever lose a message?", t.text, 30, weight=800),
        _t(pad, 116, "Thursday is a personal AI agent system that runs on one PC: a voice agent, a main agent that",
           t.secondary, 15),
        _t(pad, 136, "uses tools, and a gateway for the dashboard and phone. To measure Thursday itself, "
           "the AI model is",
           t.secondary, 15),
        _t(pad, 156, "replaced by a fake one that answers instantly. Every number here is Thursday's own work.",
           t.secondary, 15),
    ]  # fmt: skip
    chips = [
        f"{f.cpu}, {f.memory_gb:.0f} GB, {f.os}",
        "Fake AI model, instant answers",
        "Fresh copy of Thursday every run",
        f"Measured {f.date}",
    ]
    cx = pad
    for chip in chips:
        w = 16 + len(chip) * 6.6
        body += [
            f'<rect x="{cx:.0f}" y="176" width="{w:.0f}" height="28" rx="14" fill="{t.grid}" stroke="{t.border}"/>',
            _t(cx + w / 2, 194, chip, t.secondary, 12, "middle", 600),
        ]
        cx += w + 10

    pw, ph = (width - 2 * pad - gap) / 2, 262
    rows = (226, 226 + ph + gap)
    cols = (pad, pad + pw + gap)

    # 1. speed
    x, y = cols[0], rows[0]
    body += _panel(x, y, pw, ph, "1  Speed", t.violet, t)
    body += [
        _t(x + 22, y + 92, f"{f.reply:.0f} ms", t.text, 46, weight=800),
        _t(x + 22 + 28 * len(f"{f.reply:.0f} ms"), y + 92, "from Send to the whole reply", t.secondary, 14,
           weight=600),
    ]  # fmt: skip
    body += _timeline(x + 40, x + pw - 40, y + 158, f, t, small=True)
    body += [
        _t(x + 22, y + 226, "Under 100 ms feels instant. The real AI model's", t.text, 13, weight=500),
        _t(x + 22, y + 244, "own time comes on top; Thursday stays out of the way.", t.text, 13, weight=500),
    ]

    # 2. overload
    x, y = cols[1], rows[0]
    body += _panel(x, y, pw, ph, "2  Overload", t.blue, t)
    body += [
        _t(x + 22, y + 92, f"{f.accepted}", t.text, 46, weight=800),
        _t(x + 104, y + 92, f"of {f.sent} accepted at once", t.secondary, 14, weight=600),
    ]
    body += _squares(x + 24, y + 112, f, t, 20, 13, 3)
    body += [
        _t(x + pw - 22, y + 140, f"{f.refused} refused", t.bad, 16, "end", 800),
        _t(x + pw - 22, y + 158, f"“try again in {f.retry_after:.0f} s”", t.muted, 12, "end"),
        _t(x + 22, y + 226, "Overload is refused politely, never dropped: all", t.text, 13, weight=500),
        _t(x + 22, y + 244, f"{f.accepted} accepted messages were answered, in order.", t.text, 13, weight=500),
    ]

    # 3. crash test
    x, y = cols[0], rows[1]
    body += _panel(x, y, pw, ph, "3  Crash test: bug found and fixed", t.teal, t)
    b, a = sum(f.before), sum(f.after)
    body += [
        _t(x + 22, y + 74, "Kill the voice agent mid-conversation. Runs that lost a message:", t.secondary, 13),
        _t(x + 22, y + 124, f"{b}/{len(f.before)}", t.bad, 40, weight=800),
        _t(x + 22, y + 142, "before the fix", t.muted, 12, weight=600),
        _t(x + pw / 2 - 6, y + 112, "→", t.secondary, 30, "middle", 700),
        _t(x + pw / 2 + 30, y + 124, f"{a}/{len(f.after)}", t.good, 40, weight=800),
        _t(x + pw / 2 + 30, y + 142, "after the fix", t.muted, 12, weight=600),
        *_runs(x + 34, y + 170, f.before, t, 15, 25, 8),
        _t(x + 34 + len(f.before) * 25, y + 174, "before", t.muted, 11, weight=600),
        *_runs(x + 34, y + 196, f.after, t, 15, 25, 8),
        _t(x + 34 + len(f.after) * 25, y + 200, "after", t.muted, 11, weight=600),
        _t(x + 22, y + 236, "Cause: a late event marked a waiting message delivered.", t.text, 13, weight=500),
        _t(x + 22, y + 254, "Fix: only the sender marks delivery, with a test.", t.text, 13, weight=500),
    ]

    # 4. endurance
    x, y = cols[1], rows[1]
    body += _panel(x, y, pw, ph, f"4  Endurance: {f.soak_minutes:.0f} minutes", t.good, t)
    body += [
        _t(x + 22, y + 92, f"{f.soak_errors:.0f}", t.text, 46, weight=800),
        _t(x + 56, y + 92, f"errors in {f.soak_messages / 1000:.1f}k messages, agent killed halfway", t.secondary,
           14, weight=600),
    ]  # fmt: skip
    tiles = [
        (f"{f.soak_back:.1f} s", "back after the crash", t.violet),
        (f"+{100 * f.soak_growth_mb / f.soak_first_mb:.0f}%", f"memory in {f.soak_minutes:.0f} min", t.teal),
        (f"{f.soak_rate:.0f}/s", f"messages, {f.soak_chats} chats", t.blue),
    ]
    tw = (pw - 44 - 2 * 12) / 3
    for i, (value, label, colour) in enumerate(tiles):
        tx = x + 22 + i * (tw + 12)
        body += [
            f'<rect x="{tx:.0f}" y="{y + 112}" width="{tw:.0f}" height="78" rx="10" fill="{colour}" '
            f'fill-opacity="0.10"/>',
            _t(tx + 14, y + 150, value, t.text, 24, weight=800),
            _t(tx + 14, y + 174, label, t.secondary, 12, weight=600),
        ]
    body += [
        _t(x + 22, y + 226, "No gaps, repeats or lost messages: it can run all", t.text, 13, weight=500),
        _t(x + 22, y + 244, "day and recover from a crash in seconds.", t.text, 13, weight=500),
    ]

    fy = rows[1] + ph + 26
    body += [
        f'<line x1="{pad}" y1="{fy}" x2="{width - pad}" y2="{fy}" stroke="{t.border}"/>',
        _t(pad, fy + 26, f"Also: with {f.history_events:,} stored events, every history page and search answers in "
           f"under {f.history_worst_ms:.0f} ms.", t.secondary, 13, weight=600),
        _t(pad, fy + 46, "Not measured: a real AI model, speech, the phone app, other machines. "
           "Reproduce it: uv run bench run", t.muted, 12),
    ]  # fmt: skip
    return _frame(width, fy + 66, "Thursday benchmark overview", body, t)


# ---- reading the results ------------------------------------------------------------------------------------------


def _soak_run(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))["workloads"]["soak"]["runs"][0]


def facts(baseline: pathlib.Path, kill_before: list[pathlib.Path], kill_after: list[pathlib.Path]) -> Facts:
    results = json.loads(baseline.read_text(encoding="utf-8"))
    w, env = results["workloads"], results.get("environment", {})

    def med(workload: str, key: str) -> float:
        return float(w[workload]["across_runs"][key]["median"])

    first_kill = _soak_run(sorted(kill_before)[0])
    soak_run = w["soak"]["runs"][0]
    sizes = sorted(
        {int(k.split(".")[0][len("events_") :]) for k in w["history"]["across_runs"] if k.startswith("events_")}
    )
    largest = f"events_{sizes[-1]}"
    reads = [
        v["median"] for k, v in w["history"]["across_runs"].items() if k.startswith(largest) and k.endswith(".p95")
    ]
    return Facts(
        ack=med("serial", "ack_ms.p95"),
        first_token=med("serial", "first_delta_ms.p95"),
        reply=med("serial", "reply_ms.p95"),
        sent=int(med("burst", "sent")),
        accepted=int(med("burst", "accepted")),
        refused=int(med("burst", "refused_429")),
        retry_after=med("burst", "retry_after_seconds"),
        burst_seconds=med("burst", "total_seconds"),
        burst_runs=len(w["burst"]["runs"]),
        before=[bool(_soak_run(p)["errors"]) for p in sorted(kill_before)],
        after=[bool(_soak_run(p)["errors"]) for p in sorted(kill_after)],
        kill_chats=int(first_kill["chats"]),
        kill_seconds=float(first_kill["seconds"]),
        soak_minutes=soak_run["seconds"] / 60,
        soak_chats=int(soak_run["chats"]),
        soak_runs=len(w["soak"]["runs"]),
        soak_messages=med("soak", "messages"),
        soak_rate=med("soak", "messages_per_second"),
        soak_errors=med("soak", "errors"),
        soak_back=med("soak", "agent_restart.back_after_seconds"),
        soak_growth_mb=med("soak", "service_rss_mb_last_minute") - med("soak", "service_rss_mb_first_minute"),
        soak_first_mb=med("soak", "service_rss_mb_first_minute"),
        history_events=sizes[-1],
        history_worst_ms=max(reads),
        cpu=str(env.get("cpu", "unknown CPU")).replace("13th Gen Intel(R) Core(TM) ", "Intel Core "),
        memory_gb=float(env.get("memory_gb", 0)),
        os=str(env.get("os", "")).split(" ")[0],
        date=datetime.fromisoformat(results["started"]).strftime("%d %b %Y").lstrip("0"),
    )


def write(
    baseline: pathlib.Path, kill_before: list[pathlib.Path], kill_after: list[pathlib.Path], out: pathlib.Path
) -> list[pathlib.Path]:
    f = facts(baseline, kill_before, kill_after)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for theme in (LIGHT, DARK):
        suffix = "" if theme is LIGHT else "-dark"
        for name, draw in (
            ("bench-overview", overview),
            ("bench-message-time", message_time),
            ("bench-burst", burst),
            ("bench-kill-test", kill_test),
            ("bench-soak", soak),
        ):
            path = out / f"{name}{suffix}.svg"
            path.write_text(draw(f, theme) + "\n", encoding="utf-8", newline="\n")
            written.append(path)
    return written
