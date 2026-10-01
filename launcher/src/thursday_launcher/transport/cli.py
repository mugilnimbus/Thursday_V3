"""Command line: `thursday up` runs all services, `thursday down` stops them, `thursday status` checks them.

What `up` prints while it runs is in `console.py`.
"""

import argparse
import asyncio
import contextlib
import os
import pathlib
import signal
import sys
from collections.abc import Sequence

from thursday_launcher.application.shutdown import (
    PortKiller,
    clear_stop_request,
    forget_supervisor,
    record_supervisor,
    shut_down,
    stop_requested,
)
from thursday_launcher.application.supervisor import Supervisor
from thursday_launcher.domain.supervision import ServiceSpec
from thursday_launcher.infrastructure.processes import HttpHealthProbe
from thursday_launcher.transport.console import NAME_WIDTH, Console, display_name


def parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="thursday", description="Run and check Thursday services.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("up", help="start all services and keep them running (Ctrl+C or `thursday down` stops them)")
    sub.add_parser("down", help="stop all services, from any terminal")
    sub.add_parser("status", help="check each service's health once")
    sub.add_parser("setup", help="create .env from .env.example if needed and generate the service token")
    return parser.parse_args(argv)


async def run_up(supervisor: Supervisor, data_root: pathlib.Path, console: Console) -> int:
    stop = asyncio.Event()
    clear_stop_request(data_root)  # a request left over from an earlier run must not stop this one
    record_supervisor(data_root, os.getpid())
    why = "Ctrl+C"

    async def watch() -> None:
        nonlocal why
        while not stop.is_set():
            if stop_requested(data_root):
                why = "`thursday down`"
                stop.set()
                return
            console.check_slow()
            await asyncio.sleep(0.5)

    async def supervise() -> None:
        await supervisor.start_all()
        while not stop.is_set():
            await supervisor.tick()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=1.0)
        console.stopping(why)
        await supervisor.stop_all()
        console.stopped()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # Windows: KeyboardInterrupt path below
            loop.add_signal_handler(sig, stop.set)
    console.header()
    task = asyncio.create_task(supervise())
    watcher = asyncio.create_task(watch())
    try:
        await asyncio.shield(task)
    except (KeyboardInterrupt, asyncio.CancelledError):
        stop.set()
        await task
    finally:
        watcher.cancel()
        forget_supervisor(data_root)
    return 0


async def run_down(specs: Sequence[ServiceSpec], data_root: pathlib.Path, killer: PortKiller) -> int:
    probe = HttpHealthProbe()
    try:
        outcome = await shut_down(specs, data_root, probe, killer)
    finally:
        await probe.aclose()
    names = {str(spec.name): display_name(spec) for spec in specs}
    for name, what in outcome.items():
        print(f"  {names.get(name, name):<{NAME_WIDTH}} {what}")
    failed = "could not be stopped" in outcome.values()
    if failed:
        print("\nSome services could not be stopped. Close them in Task Manager, or restart the PC.")
    elif all(what == "was not running" for what in outcome.values()):
        print("\nNothing was running.")
    else:
        print("\nAll services are stopped.")
    return 1 if failed else 0


async def run_status(specs: Sequence[ServiceSpec]) -> int:
    probe = HttpHealthProbe()
    try:
        results = await asyncio.gather(*(probe.is_healthy(spec) for spec in specs))
    finally:
        await probe.aclose()
    for spec, healthy in zip(specs, results, strict=True):
        print(f"  {display_name(spec):<{NAME_WIDTH}} {'up' if healthy else 'DOWN':<6} port {spec.port}")
    up = sum(results)
    print()
    if up == len(specs):
        print(f"All {up} services are up.")
    elif up == 0:
        print("Nothing is running. Start everything with `uv run thursday up`.")
    else:
        print(f"{up} of {len(specs)} services are up. `uv run thursday up` starts the missing ones.")
    return 0 if all(results) else 1


def exit_with(code: int) -> None:
    sys.exit(code)
