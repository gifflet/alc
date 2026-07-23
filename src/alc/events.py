# events.py — Structured per-run event log for observability.
#
# A run binds a `.jsonl` file to the current context (bind_run_log); the control
# plane calls emit() at key points (mandate/act/verify/check/flow/stage/task).
# A future UI observes any run — terminal, cron, or UI — by tailing these files.
#
# Two non-negotiable properties:
#   - Best-effort: emitting an event can NEVER crash or alter a run's outcome.
#     Every I/O or serialisation error is swallowed.
#   - Reentrant: a nested binding is a no-op, so the OUTERMOST binding wins (a
#     flow running inside a tick task writes into the task's file).
#
# stdlib only (plus the internal, stdlib-only textutil leaf) — no new dependency.
from __future__ import annotations

import contextvars
import json
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from alc.textutil import slugify

# The active run-log binding for the current context (thread / worker task).
# None -> no run is being observed here, so emit() is a no-op.
_run_log: contextvars.ContextVar["_RunLog | None"] = contextvars.ContextVar(
    "alc_run_log", default=None
)


class _RunLog:
    """A bound run log: its target path plus a lock serialising concurrent appends."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()


def _utc_now_iso() -> str:
    """Return the current UTC time as ISO-8601 with a trailing ``Z``."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@contextmanager
def bind_run_log(path: Path) -> Iterator[None]:
    """Bind ``path`` as the active run log for the current context.

    Reentrant: when a log is already bound the inner binding is a NO-OP, so the
    outermost binding wins. Creates parent directories up front. Best-effort: if
    the binding cannot be set up (e.g. the parent dir cannot be created) the
    context degrades to unbound — emit() becomes a no-op — rather than crashing
    the run.
    """
    if _run_log.get() is not None:
        # An outer binding is already active; do not shadow it.
        yield
        return

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        binding = _RunLog(path)
    except Exception:
        # A broken binding must never crash a run — degrade to unbound.
        yield
        return

    token = _run_log.set(binding)
    try:
        yield
    finally:
        _run_log.reset(token)


def emit(event: str, **payload: object) -> None:
    """Append one JSON line describing ``event`` to the bound run log.

    No-op when no log is bound. The line is
    ``{"ts": "<ISO-8601 UTC Z>", "event": event, **payload}``. Best-effort: any
    I/O or serialisation error is swallowed so event emission can never alter a
    run's outcome. Appends are serialised by the binding's lock (thread-safe).
    """
    binding = _run_log.get()
    if binding is None:
        return

    try:
        record = {"ts": _utc_now_iso(), "event": event, **payload}
        # default=str keeps non-JSON-native values (e.g. Path) best-effort.
        line = json.dumps(record, default=str) + "\n"
        with binding.lock:
            with open(binding.path, "a", encoding="utf-8") as fh:
                fh.write(line)
    except Exception:
        # Observability is strictly best-effort — never let it surface.
        pass


def current_run_log_path() -> Path | None:
    """Return the path bound by the innermost active `bind_run_log`, or None.

    Lets a leaf that needs a stable, human-correlatable id for "the current
    run" (e.g. e2e evidence capture, roadmap-phase-5.md T6) reuse the SAME
    stem `alc runs show <stem>` already reads by, instead of minting a second
    one. None when no run log is bound (mirrors emit()'s own no-op contract).
    """
    binding = _run_log.get()
    return binding.path if binding is not None else None


def new_run_log_path(runs_dir: Path, kind: str, label: str) -> Path:
    """Return a fresh, time-ordered run-log path under ``runs_dir``.

    The filename is ``<UTCts>-<kind>-<slug>-<hex6>.jsonl`` where ``UTCts`` is
    ``YYYYMMDDTHHMMSS`` (lexicographically sortable by time), ``slug`` is the
    kebab-case ``label`` truncated to ~40 chars, and ``hex6`` is six hex chars of
    a uuid4 (a collision guard within the same second).
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    slug = slugify(label) or "run"
    hex6 = uuid.uuid4().hex[:6]
    return runs_dir / f"{ts}-{kind}-{slug}-{hex6}.jsonl"
