import shutil
import subprocess
import sys
import time

import pytest
from thursday_main_agent.infrastructure.power import SystemdPower

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or shutil.which("systemd-inhibit") is None, reason="needs Linux with systemd-inhibit"
)


def held() -> bool:
    out = subprocess.run(["systemd-inhibit", "--list", "--no-pager"], capture_output=True, text=True).stdout
    return "A task is running" in out


def wait_for(expected: bool) -> bool:
    deadline = time.monotonic() + 5
    while held() != expected and time.monotonic() < deadline:
        time.sleep(0.1)
    return held() == expected


def test_a_task_holds_a_sleep_lock_until_it_ends() -> None:
    power = SystemdPower()
    try:
        power.keep_awake(True)
        assert wait_for(True), "the lock is held while a task runs"
        power.keep_awake(True)
        power.keep_awake(False)
        assert wait_for(False), "and released when none runs"
    finally:
        power.keep_awake(False)
