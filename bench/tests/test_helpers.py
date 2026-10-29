import json
import pathlib

import pytest
from thursday_bench import fake_model
from thursday_bench.stack import _is_launcher
from thursday_bench.stats import across_runs, percentile, summary


def test_percentile_interpolates_between_the_two_nearest_values():
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([10], 99) == 10
    assert percentile([1, 2, 3, 4, 5], 100) == 5


def test_summary_reports_count_and_spread():
    result = summary([float(n) for n in range(1, 101)])
    assert result["n"] == 100
    assert result["p50"] == 50.5
    assert result["min"] == 1
    assert result["max"] == 100


def test_across_runs_gives_median_range_and_spread():
    runs = [{"a": {"p95": 10.0}, "errors": 0}, {"a": {"p95": 12.0}, "errors": 0}, {"a": {"p95": 11.0}, "errors": 1}]
    result = across_runs(runs)
    assert result["a.p95"] == {"median": 11.0, "min": 10.0, "max": 12.0, "spread_percent": 18.2, "runs": 3}
    assert result["errors"]["median"] == 0


def test_the_fake_model_streams_the_reply_and_ends_with_usage():
    events = [
        json.loads(chunk.split("data: ", 1)[1])
        for chunk in "".join(fake_model.stream_reply("hi")).split("\n\n")
        if chunk
    ]
    assert events[0]["type"] == "response.created"
    deltas = [e["delta"] for e in events if e["type"] == "response.output_text.delta"]
    assert "".join(deltas) == fake_model.REPLY
    assert len(deltas) <= fake_model.PIECES
    assert events[-1]["type"] == "response.completed"
    assert events[-1]["response"]["usage"]["output_tokens"] > 0
    assert [e["sequence_number"] for e in events] == list(range(len(events)))


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["/x/.venv/bin/python", "-m", "thursday_launcher", "up"], True),
        (["/x/.venv/bin/python", "/x/.venv/bin/thursday", "up"], True),
        (["/usr/bin/bash", "-c", "pgrep -af thursday_launcher"], False),
        (["/usr/bin/python3", "-m", "thursday_bench", "run"], False),
        ([], False),
    ],
)
def test_only_a_real_launcher_counts_as_a_running_stack(arguments, expected):
    assert _is_launcher(arguments) is expected


def test_the_pictures_are_drawn_from_the_results_in_light_and_dark(tmp_path: pathlib.Path) -> None:
    from thursday_bench.charts import write

    def runs(values: dict[str, float]) -> dict[str, dict[str, float]]:
        return {k: {"median": v} for k, v in values.items()}

    workloads = {
        "serial": {"across_runs": runs({"ack_ms.p95": 6.87, "first_delta_ms.p95": 29.4, "reply_ms.p95": 63.2})},
        "burst": {
            "runs": [{}] * 5,
            "across_runs": runs(
                {"sent": 120, "accepted": 101, "refused_429": 19, "retry_after_seconds": 30, "total_seconds": 5.4}
            ),
        },
        "soak": {
            "runs": [{"seconds": 1800, "chats": 20}] * 2,
            "across_runs": runs(
                {
                    "messages": 32762,
                    "messages_per_second": 18.2,
                    "errors": 0,
                    "agent_restart.back_after_seconds": 3.0,
                    "service_rss_mb_first_minute": 549.0,
                    "service_rss_mb_last_minute": 561.0,
                }
            ),
        },
        "history": {"across_runs": runs({"events_100000.search_rare_word_ms.p95": 6.9, "events_1000.x.p95": 1.0})},
    }
    baseline = tmp_path / "results.json"
    environment = {"cpu": "Test CPU", "memory_gb": 31, "os": "Linux 7"}
    started = "2026-10-29T13:52:14+00:00"
    results = {"started": started, "environment": environment, "workloads": workloads}
    baseline.write_text(json.dumps(results), encoding="utf-8")
    kill = []
    for i, errors in enumerate([1, 0, 0]):
        path = tmp_path / f"run-{i}.json"
        run = {"workloads": {"soak": {"runs": [{"errors": errors, "chats": 5, "seconds": 60}]}}}
        path.write_text(json.dumps(run), encoding="utf-8")
        kill.append(path)
    paths = write(baseline, kill[:2], kill[2:], tmp_path / "out")
    assert len(paths) == 10 and {p.name for p in paths} >= {"bench-overview.svg", "bench-overview-dark.svg"}
    overview = (tmp_path / "out" / "bench-overview.svg").read_text(encoding="utf-8")
    for shown in ("63 ms", "101", "1/2", "0/1", "32.8k messages", "100,000 stored events", "under 7 ms", "29 Oct 2026"):
        assert shown in overview, shown
