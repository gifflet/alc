# metrics.py — Per-project metric ledger: read/write the JSONL ledger of
# metric-check measurements (roadmap-phase-4.md T2), plus the pure comparison
# rule the Verifier judges a fresh measurement against.
#
# "Checks are law" extends to numbers here: the engine never judges a metric —
# it produces the number, and this module (called from the Verifier) is where
# the control plane compares it against the most recent ACCEPTED measurement
# and decides pass/fail. A number the model reports about itself is not a
# measurement; only a command's stdout, run by the Verifier, is.
#
# The ledger follows loop.append_ledger's shape: one JSON line per record,
# appended best-effort so a write failure (e.g. a read-only filesystem) can
# never bring down the run it is merely observing.
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from alc.models import MetricRecord


def ledger_path(metrics_dir: Path) -> Path:
    """Return the path to the per-project metric ledger JSONL."""
    return metrics_dir / "metrics.jsonl"


def append_measurement(path: Path, record: MetricRecord) -> None:
    """Append one measurement as a JSON line (creating the parent dir if needed).

    Best-effort, mirroring ``loop.append_ledger``: an OSError (e.g. a read-only
    filesystem) is swallowed rather than failing the check it is recording.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(record.model_dump_json() + "\n")
    except OSError:
        pass


def read_measurements(path: Path, check: str | None = None) -> list[MetricRecord]:
    """Return every MetricRecord in *path*, in ledger (chronological) order.

    Best-effort: an unreadable file or a malformed line is skipped rather than
    aborting the whole read — mirrors ``checks._iter_check_finished``. An
    absent *path* yields an empty list. When *check* is given, only that
    check's records are returned.
    """
    if not path.exists():
        return []
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []

    records: list[MetricRecord] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = MetricRecord.model_validate_json(line)
        except ValueError:
            continue
        if check is not None and record.check != check:
            continue
        records.append(record)
    return records


def latest_measurement(path: Path, check: str) -> MetricRecord | None:
    """Return the most recently recorded measurement for *check* — ANY outcome
    (passed or failed) — or None. Read-side use only (e.g. ``alc metrics``
    wants the full series); the Verifier's baseline is NEVER this — see
    ``latest_accepted_measurement``.
    """
    records = read_measurements(path, check=check)
    return records[-1] if records else None


def latest_accepted_measurement(path: Path, check: str) -> MetricRecord | None:
    """Return the most recent ACCEPTED measurement for *check*, or None.

    This is the ONLY thing a metric check may judge a fresh value against
    (verifier.py). A value that itself failed its tolerance check must never
    become the next baseline — that would let a single regression quietly
    become the new normal, one bad run at a time (roadmap-phase-4.md T2). Every
    measurement is still recorded either way (an honest history); this just
    never selects a rejected one as the goalpost.
    """
    for record in reversed(read_measurements(path, check=check)):
        if record.passed:
            return record
    return None


def within_tolerance(
    value: float,
    baseline: float,
    direction: Literal["lower_is_better", "higher_is_better"],
    tolerance_pct: float,
) -> bool:
    """Return True when *value* is acceptable against *baseline* per *direction*.

    ``tolerance_pct`` is a percentage of *baseline*, applied on the side that
    would otherwise count as a regression:
      - lower_is_better: value may grow up to baseline * (1 + tolerance_pct/100).
      - higher_is_better: value may shrink down to baseline * (1 - tolerance_pct/100).
    """
    slack = baseline * (tolerance_pct / 100.0)
    if direction == "lower_is_better":
        return value <= baseline + slack
    return value >= baseline - slack


# ---------------------------------------------------------------------------
# `alc metrics` (roadmap-phase-4.md T3) — the ledger read back as a time series.
# ---------------------------------------------------------------------------


@dataclass
class MetricPoint:
    """One measurement in a metric's time series, with context vs the point before it.

    ``delta``/``trend`` describe the RAW numeric movement only (not whether it
    is good or bad for that check — the ledger does not persist ``direction``,
    only the Blueprint's Check declaration does, and a check name is not
    guaranteed to map to exactly one Blueprint). ``delta``/``trend`` are None/"n/a"
    for a series' first point (nothing to compare against).

    ``passed`` mirrors ``MetricRecord.passed`` — whether the Verifier ACCEPTED
    this measurement at record time. A reader needs this to tell which points
    in the series were actually the check's baseline at some point (accepted)
    versus a rejected outlier that never moved the goalpost.
    """

    ts: float
    value: float
    run: str
    delta: float | None
    trend: Literal["up", "down", "flat", "n/a"]
    passed: bool


def metric_series(path: Path, check: str | None = None) -> dict[str, list[MetricPoint]]:
    """Group the ledger's records into a per-check chronological time series.

    Args:
        path: The ledger JSONL path.
        check: When set, only this check's series is included.

    Returns:
        {check name: [MetricPoint, ...]} in chronological order, keyed by every
        check name found in the ledger (or just *check*, when it has history).
        Empty when the ledger is absent/empty or *check* has no records.
    """
    by_check: dict[str, list[MetricRecord]] = {}
    for record in read_measurements(path, check=check):
        by_check.setdefault(record.check, []).append(record)

    series: dict[str, list[MetricPoint]] = {}
    for name, records in by_check.items():
        points: list[MetricPoint] = []
        previous: float | None = None
        for record in records:
            if previous is None:
                delta: float | None = None
                trend: Literal["up", "down", "flat", "n/a"] = "n/a"
            else:
                delta = record.value - previous
                trend = "flat" if delta == 0 else ("up" if delta > 0 else "down")
            points.append(
                MetricPoint(
                    ts=record.ts,
                    value=record.value,
                    run=record.run,
                    delta=delta,
                    trend=trend,
                    passed=record.passed,
                )
            )
            previous = record.value
        series[name] = points
    return series
