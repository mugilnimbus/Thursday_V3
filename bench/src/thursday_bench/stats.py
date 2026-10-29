"""Small statistics helpers: percentiles, one summary per metric, and the spread across runs."""

import statistics
from typing import Any


def percentile(values: list[float], q: float) -> float:
    """The q-th percentile (0 to 100) with linear interpolation between the two nearest values."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 100
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def summary(values: list[float]) -> dict[str, float]:
    """p50, p95, p99, smallest, largest and the count of one list of measurements."""
    return {
        "n": len(values),
        "p50": round(percentile(values, 50), 2),
        "p95": round(percentile(values, 95), 2),
        "p99": round(percentile(values, 99), 2),
        "min": round(min(values), 2) if values else float("nan"),
        "max": round(max(values), 2) if values else float("nan"),
    }


def flatten(prefix: str, value: Any, out: dict[str, float]) -> None:
    """{'a': {'p95': 3}} becomes {'a.p95': 3}. Only numbers are kept."""
    if isinstance(value, dict):
        for key, inner in value.items():
            flatten(f"{prefix}.{key}" if prefix else str(key), inner, out)
    elif isinstance(value, bool | int | float):
        out[prefix] = float(value)


def across_runs(runs: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """For each metric: the median over the runs, the smallest and largest, and the spread as a share of the median."""
    flat_runs = []
    for run in runs:
        flat: dict[str, float] = {}
        flatten("", run, flat)
        flat_runs.append(flat)
    keys = sorted({key for flat in flat_runs for key in flat})
    result: dict[str, dict[str, float]] = {}
    for key in keys:
        values = [flat[key] for flat in flat_runs if key in flat]
        median = statistics.median(values)
        spread = (max(values) - min(values)) / abs(median) * 100 if median else 0.0
        result[key] = {
            "median": round(median, 2),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
            "spread_percent": round(spread, 1),
            "runs": len(values),
        }
    return result
