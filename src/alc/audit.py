# audit.py — Aggregate archived queue reports over a trailing time window.
#
# Reads the same done/ Gate archive the queue writes, using the same read
# pattern as ui.service.scorecard (skip an unreadable/invalid report rather
# than aborting the whole aggregation). Consumed by the `alc audit` CLI
# command; core-only, no `alc.ui` import.
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from alc.models import FlowReport

# `<int><unit>`, unit one of d(ays)/h(ours)/m(inutes) — e.g. "7d", "24h", "30m".
_SINCE_RE = re.compile(r"^(\d+)([dhm])$")
_UNIT_SECONDS = {"d": 86400, "h": 3600, "m": 60}


def parse_since(value: str) -> int:
    """Parse a relative window like "7d" / "24h" / "30m" into a second count.

    Raises ValueError — a clear message, not a traceback — when *value* does
    not match the ``<int><unit>`` shape.
    """
    match = _SINCE_RE.match(value.strip())
    if not match:
        raise ValueError(
            f"invalid --since value '{value}'; expected e.g. '7d', '24h', '30m'"
        )
    amount, unit = match.groups()
    return int(amount) * _UNIT_SECONDS[unit]


@dataclass
class AuditWindow:
    """Aggregate of every archived queue report at/after ``since_epoch``."""

    since_epoch: float
    tasks_total: int
    tasks_ok: int
    tasks_failed: int
    span_total: int
    span_avg: float
    passes_total: int
    passes_avg: float
    streak_total: int
    streak_avg: float
    touch_total: int
    touch_avg: float
    changed_files_total: int
    input_tokens_total: int
    output_tokens_total: int
    cost_usd_total: float


def audit_window(
    done_dir: Path, since_epoch: float, extra_report_dir: Path | None = None
) -> AuditWindow:
    """Aggregate the archived reports (``*.report.json``) at/after *since_epoch*.

    Reads the queue's ``done/`` reports and, when *extra_report_dir* is given, the
    ``runs/`` reports a direct ``alc run`` archives there — so the window counts
    INTERACTIVE runs too, not only queue-drained (``alc tick``) work. A report's
    archive-file mtime (the Gate write time) decides whether it falls inside the
    window. Mirrors ``ui.service.scorecard``'s read pattern: an unreadable or invalid
    archive is skipped, not fatal. Absent dirs contribute nothing.

    Per-task totals come from the FlowReport's own aggregate ``scorecard``
    (already summed across stages, like ``ui.service.scorecard``); changed
    files and Usage are summed per STAGE, since only RunReport carries them.
    """
    tasks_total = tasks_ok = tasks_failed = 0
    span_total = passes_total = streak_total = touch_total = 0
    changed_files_total = 0
    input_tokens_total = output_tokens_total = 0
    cost_usd_total = 0.0

    report_dirs = [done_dir] + ([extra_report_dir] if extra_report_dir is not None else [])
    report_files = sorted(
        f for d in report_dirs if d.is_dir() for f in d.glob("*.report.json")
    )
    for report_file in report_files:
        if report_file.stat().st_mtime < since_epoch:
            continue
        try:
            report = FlowReport.model_validate_json(report_file.read_text())
        except (ValidationError, OSError):
            continue

        tasks_total += 1
        if report.success:
            tasks_ok += 1
        else:
            tasks_failed += 1
        span_total += report.scorecard.span
        passes_total += report.scorecard.passes
        streak_total += report.scorecard.streak
        touch_total += report.scorecard.touch

        for stage in report.stages:
            changed_files_total += len(stage.changed_files)
            usage = stage.usage
            if usage is None:
                continue
            if usage.input_tokens is not None:
                input_tokens_total += usage.input_tokens
            if usage.output_tokens is not None:
                output_tokens_total += usage.output_tokens
            if usage.cost_usd is not None:
                cost_usd_total += usage.cost_usd

    def _avg(total: int) -> float:
        return total / tasks_total if tasks_total else 0.0

    return AuditWindow(
        since_epoch=since_epoch,
        tasks_total=tasks_total,
        tasks_ok=tasks_ok,
        tasks_failed=tasks_failed,
        span_total=span_total,
        span_avg=_avg(span_total),
        passes_total=passes_total,
        passes_avg=_avg(passes_total),
        streak_total=streak_total,
        streak_avg=_avg(streak_total),
        touch_total=touch_total,
        touch_avg=_avg(touch_total),
        changed_files_total=changed_files_total,
        input_tokens_total=input_tokens_total,
        output_tokens_total=output_tokens_total,
        cost_usd_total=cost_usd_total,
    )
