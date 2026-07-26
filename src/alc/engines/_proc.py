# _proc.py — shared process-tree reaping for the engine adapters.
#
# An engine spawns `claude`/`gemini` with start_new_session=True, so the child is
# the leader of a NEW process group whose id == its pid. That lets us signal the
# whole group — the child AND every descendant it spawned (Bash-tool processes,
# MCP servers) — in one call. A bare `proc.kill()` reaps only the direct child,
# orphaning those descendants to keep burning tokens after a stop or timeout.
# Both adapters route their timeout AND interrupt paths through this one helper.
from __future__ import annotations

import os
import signal
import subprocess


def terminate_process_group(proc: subprocess.Popen) -> None:
    """Best-effort: SIGKILL the whole process group led by *proc*; never raise.

    Falls back to a bare ``proc.kill()`` on any error — a non-POSIX platform
    (no ``os.killpg``/``os.getpgid`` -> AttributeError), a PermissionError, or a
    race where the process already exited (ProcessLookupError). Safe to call from
    a timeout handler or an interrupt path: it always attempts to reap and swallows
    every failure so it can never mask the original error being handled.
    """
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, AttributeError, OSError):
        try:
            proc.kill()
        except (ProcessLookupError, OSError):
            pass  # already gone / cannot signal — nothing left to reap
