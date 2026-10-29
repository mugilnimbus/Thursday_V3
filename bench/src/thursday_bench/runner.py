"""Run the workloads, each in a fresh stack, and keep the raw results."""

import asyncio
import datetime
import json
import pathlib
import shutil
import time
from typing import Any

from thursday_bench import environment, workloads
from thursday_bench.gateway import Gateway
from thursday_bench.stack import Stack, StackError
from thursday_bench.stats import across_runs

QUIET_LIMIT_PERCENT = 40.0

# (workload, keyword arguments, runs)
FULL: dict[str, tuple[dict[str, Any], int]] = {
    "serial": ({"messages": 200}, 5),
    "burst": ({"messages": 120}, 5),
    "many": ({"chats": 20, "seconds": 300}, 3),
    "history": ({"sizes": (1_000, 10_000, 100_000)}, 5),
    "soak": ({"chats": 20, "seconds": 1800}, 2),
}
QUICK: dict[str, tuple[dict[str, Any], int]] = {
    "serial": ({"messages": 20}, 1),
    "burst": ({"messages": 120}, 1),
    "many": ({"chats": 5, "seconds": 20}, 1),
    "history": ({"sizes": (500, 2_000)}, 1),
    "soak": ({"chats": 5, "seconds": 60}, 1),
}


async def one_run(name: str, kwargs: dict[str, Any], folder: pathlib.Path) -> dict[str, Any]:
    stack = Stack(folder)
    started = time.perf_counter()
    try:
        stack.start()
        async with Gateway(stack) as gw:
            await gw.wait_until_ready()
            startup = time.perf_counter() - started
            result = await workloads.WORKLOADS[name](gw, stack, **kwargs)
        return {"startup_seconds": round(startup, 1), **result}
    finally:
        stack.stop()


def run(names: list[str], quick: bool, runs: int | None, out: pathlib.Path) -> pathlib.Path:
    plan = QUICK if quick else FULL
    out.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {
        "started": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "mode": "quick" if quick else "full",
        "environment": environment.collect({name: plan[name][0] for name in names}),
        "workloads": {},
    }
    target = out / "results.json"
    for name in names:
        kwargs, default_runs = plan[name]
        count = runs or default_runs
        collected: list[dict[str, Any]] = []
        for index in range(count):
            load = environment.load_before_run()
            if load > QUIET_LIMIT_PERCENT:
                raise StackError(f"The PC is busy ({load:.0f}% CPU). Close what runs and start again.")
            print(f"[{name}] run {index + 1} of {count} (PC load before: {load:.0f}%)", flush=True)
            folder = out / "raw" / f"{name}-{index + 1}"
            shutil.rmtree(folder, ignore_errors=True)
            result: dict[str, Any]
            try:
                result = asyncio.run(one_run(name, kwargs, folder))
            except Exception as exc:
                result = {"failed": f"{type(exc).__name__}: {exc}"}
            result["pc_load_before_percent"] = load
            collected.append(result)
            results["workloads"][name] = {"runs": collected}
            target.write_text(json.dumps(results, indent=2), encoding="utf-8")
        ok = [r for r in collected if "failed" not in r]
        results["workloads"][name] = {
            "runs": collected,
            "across_runs": across_runs(ok),
            "failed_runs": len(collected) - len(ok),
        }
        target.write_text(json.dumps(results, indent=2), encoding="utf-8")
        for index in range(count):  # the stack's data is large; keep the logs, drop the databases
            shutil.rmtree(out / "raw" / f"{name}-{index + 1}" / "data", ignore_errors=True)
    return target
