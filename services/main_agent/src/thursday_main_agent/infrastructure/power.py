"""Keeping the PC awake.

Windows: a power request via `SetThreadExecutionState` (no package needed). The request belongs to the calling
thread, so it is always made from the event-loop thread.
Linux with systemd: a sleep inhibitor lock, held by a `systemd-inhibit` child process while a task needs it.
Anywhere else this does nothing.
"""

import atexit
import ctypes
import logging
import shutil
import subprocess
import sys
import time

log = logging.getLogger(__name__)
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


class WindowsPower:
    def keep_awake(self, on: bool) -> None:
        if sys.platform != "win32":
            return
        flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0)
        if ctypes.windll.kernel32.SetThreadExecutionState(flags) == 0:  # pyright: ignore[reportAttributeAccessIssue]
            log.warning("could not change the keep-awake request")
        else:
            log.info("keep-awake %s", "on" if on else "off")


class SystemdPower:
    """Holds a systemd inhibitor lock: `systemd-inhibit` keeps the lock for as long as its child runs.

    It asks for sleep and idle first. A session that systemd does not trust (a remote one, for example) may not
    block sleep; then it asks for idle alone, which is all that session may hold.
    """

    WHAT = ("sleep:idle", "idle")

    def __init__(self) -> None:
        self._holder: subprocess.Popen[bytes] | None = None
        atexit.register(self._release)

    def keep_awake(self, on: bool) -> None:
        if on and self._holder is None:
            self._holder = self._acquire()
            if self._holder is None:
                log.warning("could not change the keep-awake request")
            else:
                log.info("keep-awake on")
        elif not on and self._holder is not None:
            self._release()
            log.info("keep-awake off")

    def _acquire(self) -> "subprocess.Popen[bytes] | None":
        program = shutil.which("systemd-inhibit")
        if program is None:
            return None
        for what in self.WHAT:
            try:
                holder = subprocess.Popen(  # noqa: S603 - fixed program and arguments
                    [
                        program,
                        f"--what={what}",
                        "--who=Thursday",
                        "--why=A task is running",
                        "--mode=block",
                        "sleep",
                        "infinity",
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError:
                return None
            time.sleep(0.3)  # a refused lock ends the program at once
            if holder.poll() is None:
                return holder
        return None

    def _release(self) -> None:
        holder, self._holder = self._holder, None
        if holder is not None and holder.poll() is None:
            holder.terminate()
            holder.wait(timeout=5)


class NoPower:
    def keep_awake(self, on: bool) -> None:
        return


def pick_power() -> "WindowsPower | SystemdPower | NoPower":
    if sys.platform == "win32":
        return WindowsPower()
    if sys.platform == "linux" and shutil.which("systemd-inhibit"):
        return SystemdPower()
    return NoPower()
