# runs.py — Read-only access to the run-log directory (`.alc/runs/*.jsonl`).
#
# Every mandate/flow/task turn appends structured JSON-lines events to its own
# run log. These readers list and tail those logs; they take an explicit
# `runs_dir` (and `stale_after`) rather than a project root, so they never
# touch the manifest — that resolution stays with the caller (`alc.ui.service`
# today, the `alc runs` CLI later).
from __future__ import annotations

import json
import time
from pathlib import Path

# A run finishes at the terminal event for its KIND (mirrors the detail view's
# buildTimeline): a flow at ``flow_finished``, a task at ``task_finished``. A
# flow/task run's inner ``mandate_finished`` lines are NOT terminal — the run
# is still live until its wrapper closes; only a bare mandate run (no flow/task
# wrapper) finishes at its own ``mandate_finished``.
_WRAPPER_STARTS = {"flow_started", "task_started"}
_WRAPPER_TERMINALS = {"flow_finished", "task_finished"}

# An interrupted run (Ctrl-C / SIGTERM) emits ``run_aborted`` as its LAST event
# (events.abort_event_on_interrupt). It is terminal for EVERY kind — a bare
# mandate, a flow, or a task run all close on it — so a killed run reads as
# finished at once instead of waiting out the staleness threshold.
_ABORT_TERMINAL = "run_aborted"


def _run_kind(stem: str) -> str:
    """Extract the run kind from a run-log stem (``<ts>-<kind>-<slug>-<hex>``)."""
    parts = stem.split("-")
    return parts[1] if len(parts) > 1 else ""


def _run_finished(path: Path) -> bool:
    """Return True when the run reached the terminal event for its kind.

    Mirrors the detail view (buildTimeline) so the runs list and the run detail
    never disagree: a flow/task run's inner ``mandate_finished`` is not terminal
    — only ``flow_finished`` / ``task_finished`` closes it; a bare mandate run
    (no flow/task wrapper) closes at its ``mandate_finished``. An interrupted
    run's ``run_aborted`` is terminal for every kind.
    """
    try:
        lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    except OSError:
        return False
    events: set[str] = set()
    for ln in lines:
        try:
            event = json.loads(ln).get("event")
        except json.JSONDecodeError:
            continue
        if isinstance(event, str):
            events.add(event)
    # An abort is terminal for any kind, so it is checked before the wrapper.
    if _ABORT_TERMINAL in events:
        return True
    if events & _WRAPPER_TERMINALS:
        return True
    return not (events & _WRAPPER_STARTS) and "mandate_finished" in events


def _net_lines(path: Path) -> int | None:
    """Return net lines (adds - dels) summed across every `mandate_finished`
    event's diffstat in *path*'s run log (roadmap-phase-4.md T4).

    Sums across ALL such events, not just one — a flow/task run's log holds one
    `mandate_finished` per stage, so this reflects the whole run, not just its
    last stage. None when the log carries no diffstat at all (every event's
    diffstat was null, or there is no `mandate_finished` event), matching
    Diffstat's own "not computable or nothing changed" semantics — never a
    misleading 0.
    """
    try:
        lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    except OSError:
        return None

    total = 0
    found = False
    for ln in lines:
        try:
            event = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("event") != "mandate_finished":
            continue
        diffstat = event.get("diffstat")
        if not isinstance(diffstat, dict):
            continue
        adds, dels = diffstat.get("adds"), diffstat.get("dels")
        if not isinstance(adds, int) or not isinstance(dels, int):
            continue
        total += adds - dels
        found = True
    return total if found else None


# Grace beyond a turn's max lifetime before a still-unfinished run is deemed dead.
# A running turn is killed at manifest.default_timeout_s, so a run whose log has
# gone quiet for longer than that (plus this margin) has no live process behind
# it — it was interrupted, not running.
STALE_MARGIN_S = 300


def _run_stale(mtime: float, finished: bool, stale_after: float, now: float) -> bool:
    """True when an UNFINISHED run's log has been idle past the interrupted threshold."""
    return not finished and (now - mtime) > stale_after


def list_runs(runs_dir: Path, stale_after: float, limit: int = 50, offset: int = 0) -> dict:
    """List run logs (newest first) with simple pagination."""
    if not runs_dir.is_dir():
        return {"runs": [], "total": 0}

    files = sorted(
        runs_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    total = len(files)
    page = files[offset : offset + limit]
    now = time.time()
    runs = []
    for path in page:
        st = path.stat()
        finished = _run_finished(path)
        runs.append(
            {
                "stem": path.stem,
                "kind": _run_kind(path.stem),
                "mtime": st.st_mtime,
                "size": st.st_size,
                "finished": finished,
                "stale": _run_stale(st.st_mtime, finished, stale_after, now),
                "net_lines": _net_lines(path),
            }
        )
    return {"runs": runs, "total": total}


def read_run(runs_dir: Path, stem: str, stale_after: float, offset: int = 0) -> dict:
    """Return parsed events for one run from line ``offset`` (for incremental tail).

    ``next_offset`` is the total line count, to be passed back as ``offset`` on
    the next poll so only new lines are returned. Raises ``FileNotFoundError``
    when the run log does not exist.
    """
    path = runs_dir / f"{stem}.jsonl"
    if not path.is_file():
        raise FileNotFoundError(f"no run '{stem}'")
    lines = path.read_text().splitlines()
    events = []
    for line in lines[offset:]:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    stale = _run_stale(path.stat().st_mtime, _run_finished(path), stale_after, time.time())
    return {"events": events, "next_offset": len(lines), "stale": stale}
