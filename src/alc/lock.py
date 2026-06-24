# lock.py — A non-blocking inter-process lock for `alc tick`.
# Prevents overlapping cron ticks from processing the same task twice. Uses
# fcntl.flock (POSIX advisory lock): the OS releases it automatically when the
# process exits or crashes, so there are no stale lock files. On platforms
# without fcntl the lock degrades to a no-op (always "acquired").
from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX platforms (e.g. Windows)
    fcntl = None


@contextlib.contextmanager
def tick_lock(lock_path: Path) -> Iterator[bool]:
    """Acquire a non-blocking exclusive lock at *lock_path*.

    Args:
        lock_path: Path to the lock file (created if missing).

    Yields:
        True if the lock was acquired (the caller may proceed); False if another
        holder already owns it (the caller should skip). Released automatically
        on exit, and by the OS if the process dies.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a")  # kept open for the lock's lifetime
    try:
        if fcntl is None:
            # No advisory locking available: degrade to a no-op lock.
            yield True
            return
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            # Another process already holds the lock.
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        handle.close()
