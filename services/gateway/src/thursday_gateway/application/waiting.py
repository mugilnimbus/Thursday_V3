"""Sleep until either event is set or the timeout passes."""

import asyncio
import contextlib


async def wait_any(*events: asyncio.Event, timeout: float) -> None:
    waiters = [asyncio.create_task(e.wait()) for e in events]
    try:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED), timeout=timeout)
    finally:
        for waiter in waiters:
            waiter.cancel()
