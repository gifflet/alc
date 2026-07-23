# signals.py — Signal intake (roadmap-phase-5.md T1): the typed JSON files a
# real-usage source (an error tracker, user feedback, an issue tracker, a code
# review) drops into `manifest.signals_dir`, and the read/archive functions
# the `signals` replenish kind (loop.py) and `alc signal` (cli.py) both build on.
#
# A signal is DATA, not a command: turning one into a demand (loop.py's
# "signals" replenish, via `conduct.dispatch_enqueue`) goes through the same
# Policy Gate, isolation, and retry as any hand-written queue task. This
# module never enqueues anything itself.
#
# File-per-signal under signals_dir (mirrors queue_dir's *.yaml Source),
# moved to signals_dir/done/ once consumed (mirrors queue.py's done/ archive).
from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from alc.models import Signal
from alc.textutil import slugify as _slugify


def ingest(signals_dir: Path, signal: Signal) -> Path:
    """Write *signal* as a typed JSON file under *signals_dir*; return its path.

    A direct write (mirrors ``conduct.dispatch_enqueue``'s queue-task write):
    a failure (e.g. a read-only filesystem) is NOT swallowed here — it
    surfaces to the caller (``alc signal ingest`` reports it as ``[ERROR]``)
    rather than silently losing a signal the operator explicitly asked to
    record.
    """
    signals_dir.mkdir(parents=True, exist_ok=True)
    uid = uuid.uuid4().hex[:8]
    slug = _slugify(signal.title) or signal.kind
    path = signals_dir / f"{signal.kind}-{slug}-{uid}.json"
    path.write_text(signal.model_dump_json(indent=2))
    return path


@dataclass
class PendingSignal:
    """One unconsumed signal: its file path (needed to archive it) plus the parsed model."""

    path: Path
    signal: Signal


def read_signals(signals_dir: Path) -> list[PendingSignal]:
    """Return every pending signal in *signals_dir*, oldest (by ``ts``) first.

    Best-effort, mirroring ``queue.outstanding_failures`` /
    ``metrics.read_measurements``: an absent directory yields an empty list;
    a malformed or unreadable file is skipped rather than aborting the whole
    read. The ``done/`` subdirectory is naturally excluded — ``glob("*.json")``
    only sees files directly under *signals_dir*.
    """
    if not signals_dir.exists():
        return []
    pending: list[PendingSignal] = []
    for path in sorted(signals_dir.glob("*.json")):
        try:
            signal = Signal.model_validate_json(path.read_text())
        except (OSError, ValueError):
            continue  # unreadable / invalid signal file -> skip
        pending.append(PendingSignal(path=path, signal=signal))
    pending.sort(key=lambda p: p.signal.ts)
    return pending


def archive_signal(signals_dir: Path, signal_path: Path) -> None:
    """Move a consumed signal file into ``signals_dir/done/``, mirroring the queue's archive.

    Best-effort: any OSError (the file was already archived/removed by a
    prior crashed attempt, a read-only filesystem, ...) is swallowed rather
    than raised. Combined with the "enqueue THEN archive" order the
    ``signals`` replenish uses (``loop.py``), the worst case of a crash
    between the two steps is a signal re-processed on the next cycle (one
    duplicate demand) — never a lost signal, never a traceback.
    """
    done_dir = signals_dir / "done"
    try:
        done_dir.mkdir(parents=True, exist_ok=True)
        signal_path.rename(done_dir / signal_path.name)
    except OSError:
        pass
