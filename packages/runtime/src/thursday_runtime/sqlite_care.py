"""Keeping a service's SQLite files small.

Deleting rows does not shrink a SQLite file: the space is kept for later rows, and the deleted rows' bytes stay
readable in it until they are overwritten. Compacting rewrites the file without that unused space. It needs the
file to itself, so a service does it at start, before it opens the file for work.
"""

import logging
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)
MIN_FREE_BYTES = 8 * 1024 * 1024
MIN_FREE_SHARE = 0.25


def compact_if_worthwhile(
    path: Path, *, min_free_bytes: int = MIN_FREE_BYTES, min_free_share: float = MIN_FREE_SHARE
) -> int:
    """Compact the file when enough of it is unused. Returns the bytes given back; 0 when nothing was done.

    A file that is missing, busy or unreadable is left alone: this never stops a service from starting.
    """
    if not path.is_file():
        return 0
    try:
        db = sqlite3.connect(path, isolation_level=None, timeout=2)
    except sqlite3.Error:
        return 0
    try:
        page = int(db.execute("pragma page_size").fetchone()[0])
        pages = int(db.execute("pragma page_count").fetchone()[0])
        free = int(db.execute("pragma freelist_count").fetchone()[0])
        if free * page < min_free_bytes or free < pages * min_free_share:
            return 0
        db.execute("vacuum")
        db.execute("pragma wal_checkpoint(truncate)")
        after = int(db.execute("pragma page_count").fetchone()[0])
    except sqlite3.Error as exc:
        log.warning("could not compact %s (%s)", path.name, type(exc).__name__)
        return 0
    finally:
        db.close()
    given_back = max(0, (pages - after) * page)
    log.info("compacted %s: %.1f MB given back", path.name, given_back / 1e6)
    return given_back


def compact_all(paths: list[Path]) -> int:
    return sum(compact_if_worthwhile(path) for path in paths)
