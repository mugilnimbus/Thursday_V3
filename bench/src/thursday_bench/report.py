"""Turn results.json into report.md: one table per workload, each number as median and range over the runs."""

import json
import pathlib
from typing import Any

# (label, metric key, unit, provisional target as (limit, "<" or "=="))
HEADLINES: dict[str, list[tuple[str, str, str, tuple[float, str] | None]]] = {
    "serial": [
        ("Send, POST to 202, p50", "ack_ms.p50", "ms", None),
        ("Send, POST to 202, p95", "ack_ms.p95", "ms", (100, "<")),
        ("Send, POST to 202, p99", "ack_ms.p99", "ms", None),
        ("Message to first delta, p50", "first_delta_ms.p50", "ms", None),
        ("Message to first delta, p95", "first_delta_ms.p95", "ms", (250, "<")),
        ("Message to final reply, p50", "reply_ms.p50", "ms", None),
        ("Message to final reply, p95", "reply_ms.p95", "ms", None),
        ("Event lag, user message, p95", "lag_user_message_ms.p95", "ms", (250, "<")),
        ("Event lag, model call, p95", "lag_llm_call_ms.p95", "ms", (250, "<")),
        ("Event lag, reply, p95", "lag_assistant_message_ms.p95", "ms", (250, "<")),
        ("Reply p50, first quarter of messages", "reply_first_quarter_p50_ms", "ms", None),
        ("Reply p50, last quarter of messages", "reply_last_quarter_p50_ms", "ms", None),
        ("Messages with an error", "errors", "", (0, "==")),
    ],
    "burst": [
        ("Messages sent", "sent", "", None),
        ("Accepted", "accepted", "", None),
        ("Refused with 429", "refused_429", "", None),
        ("Position of the first refusal", "first_refusal_after", "", None),
        ("Retry-After", "retry_after_seconds", "s", (30, "==")),
        ("Every accepted message answered (1 = yes)", "all_accepted_answered", "", (1, "==")),
        ("Delivered in the order accepted (1 = yes)", "in_order", "", (1, "==")),
        ("Time to send all", "sending_seconds", "s", None),
        ("Time until the last reply", "total_seconds", "s", None),
    ],
    "many": [
        ("Messages per second", "messages_per_second", "", None),
        ("Stored events per second", "events_per_second", "", None),
        ("Message to final reply, p50", "reply_ms.p50", "ms", None),
        ("Message to final reply, p95", "reply_ms.p95", "ms", None),
        ("Event lag, reply, p95", "lag_assistant_message_ms.p95", "ms", (250, "<")),
        ("Error rate", "error_rate_percent", "%", (0, "==")),
        ("Service memory, first minute", "service_rss_mb_first_minute", "MB", None),
        ("Service memory, last minute", "service_rss_mb_last_minute", "MB", None),
        ("Largest outbox backlog", "outbox_backlog_max", "", None),
        ("PC CPU, median", "pc_cpu_percent_median", "%", None),
    ],
    "soak": [
        ("Messages per second", "messages_per_second", "", None),
        ("Error rate", "error_rate_percent", "%", None),
        ("Service memory, first minute", "service_rss_mb_first_minute", "MB", None),
        ("Service memory, last minute", "service_rss_mb_last_minute", "MB", None),
        ("Voice agent back after the kill", "agent_restart.back_after_seconds", "s", None),
        ("Gaps in event numbers", "seq_gaps", "", (0, "==")),
        ("Repeated event numbers", "seq_repeats", "", (0, "==")),
        ("Repeated event ids", "event_id_repeats", "", (0, "==")),
        ("User messages stored twice", "user_messages_repeated", "", (0, "==")),
    ],
}


def _cell(entry: dict[str, float] | None, unit: str) -> str:
    if entry is None:
        return "-"
    median, low, high = entry["median"], entry["min"], entry["max"]
    text = f"{median:g}{(' ' + unit) if unit else ''}"
    if entry["runs"] > 1:
        text += f" ({low:g} to {high:g}, {entry['runs']} runs)"
    return text


def _verdict(entry: dict[str, float] | None, target: tuple[float, str] | None) -> str:
    if entry is None or target is None:
        return ""
    limit, op = target
    ok = entry["median"] < limit if op == "<" else entry["median"] == limit
    return "met" if ok else "missed"


def _table(rows: list[tuple[str, str, str]]) -> list[str]:
    lines = ["| Measure | Result | Target (provisional) |", "|---|---|---|"]
    lines += [f"| {a} | {b} | {c} |" for a, b, c in rows]
    return lines


HISTORY_ROWS = [
    ("Events go in, per second", "ingest_events_per_second", ""),
    ("Gateway database on disk", "gateway_disk_mb", "MB"),
    ("Disk added per 1,000 events", "disk_bytes_per_1000_events", "bytes"),
    ("Latest 50 messages, p50", "page_latest_50_ms.p50", "ms"),
    ("Latest 50 messages, p95", "page_latest_50_ms.p95", "ms"),
    ("Older 50 messages, p95", "page_older_50_ms.p95", "ms"),
    ("Search for a common word, p50", "search_common_word_ms.p50", "ms"),
    ("Search for a common word, p95", "search_common_word_ms.p95", "ms"),
    ("Search for a rare word, p95", "search_rare_word_ms.p95", "ms"),
    ("Timeline page of 200 events, p95", "timeline_200_ms.p95", "ms"),
]


def _history_table(across: dict[str, dict[str, float]]) -> list[str]:
    sizes = sorted({int(k.split(".")[0].removeprefix("events_")) for k in across if k.startswith("events_")})
    lines = ["| Measure | " + " | ".join(f"{s:,} events" for s in sizes) + " |", "|---|" + "---|" * len(sizes)]
    for label, key, unit in HISTORY_ROWS:
        cells = [_cell(across.get(f"events_{s}.{key}"), unit) for s in sizes]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return lines


def write(results_path: pathlib.Path) -> pathlib.Path:
    data: dict[str, Any] = json.loads(results_path.read_text(encoding="utf-8"))
    env = data["environment"]
    out = ["# Benchmark results", ""]
    out += [
        f"Mode: {data['mode']}. Started {data['started']}. Commit {env['commit']}"
        f"{' (with uncommitted changes)' if env['uncommitted_changes'] else ''}.",
        "",
        f"Machine: {env['cpu']}, {env['cpu_threads']} threads, {env['memory_gb']} GB, {env['os']}, "
        f"Python {env['python']}.",
        "",
    ]
    for name, block in data["workloads"].items():
        across = block.get("across_runs", {})
        failed = block.get("failed_runs", 0)
        out += [f"## {name}", ""]
        if failed:
            reasons = "; ".join(r["failed"] for r in block["runs"] if "failed" in r)
            out += [f"{failed} run(s) failed: {reasons}", ""]
        if name in HEADLINES:
            rows = []
            for label, key, unit, target in HEADLINES[name]:
                entry = across.get(key)
                goal = ""
                if target:
                    goal = f"{target[1]} {target[0]:g}{(' ' + unit) if unit and target[1] == '<' else ''}"
                    goal += f" ({_verdict(entry, target)})" if entry else ""
                rows.append((label, _cell(entry, unit), goal))
            out += _table(rows)
        elif name == "history":
            out += _history_table(across)
        else:
            rows = [(k, _cell(v, ""), "") for k, v in across.items() if not k.endswith((".n", ".min", ".max"))]
            out += _table(rows)
        out.append("")
    target_path = results_path.with_name("report.md")
    target_path.write_text("\n".join(out), encoding="utf-8")
    return target_path
