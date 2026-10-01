"""Windows power request via `SetThreadExecutionState` (no package needed).

The request belongs to the calling thread, so it is always made from the event-loop thread.
On other platforms this does nothing.
"""

import ctypes
import logging
import sys

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
