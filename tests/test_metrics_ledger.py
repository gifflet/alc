# test_metrics_ledger.py — Hermetic tests for roadmap-phase-4.md T2 (the
# per-project metric ledger, src/alc/metrics.py) and T3 (`alc metrics
# [--check NAME] [--json]`): the time series read back from that ledger.
#
# (a) Manifest.metrics_dir.
# (b) ledger_path / append_measurement / read_measurements /
#     latest_measurement / latest_accepted_measurement.
# (c) within_tolerance — the pure comparison rule.
# (d) metric_series — the per-check time series with delta + trend + passed.
# (e) CLI — `alc metrics [--check NAME] [--json]`.
from __future__ import annotations

import argparse
import json
from pathlib import Path

from alc.cli import cmd_metrics
from alc.metrics import (
    MetricPoint,
    append_measurement,
    latest_accepted_measurement,
    latest_measurement,
    ledger_path,
    metric_series,
    read_measurements,
    within_tolerance,
)
from alc.models import Manifest, MetricRecord


def _record(check: str, value: float, ts: float, run: str = "r", passed: bool = True) -> MetricRecord:
    return MetricRecord(check=check, value=value, ts=ts, run=run, passed=passed)


# ---------------------------------------------------------------------------
# (a) Manifest.metrics_dir
# ---------------------------------------------------------------------------


class TestManifestMetricsDir:
    def test_default_value(self) -> None:
        manifest = Manifest(
            version=1,
            default_engine="mock",
            compute_tiers={"standard": {"mock": "mock-small"}},
            engines={"mock": {"type": "mock"}},
        )
        assert manifest.metrics_dir == ".alc/metrics"


# ---------------------------------------------------------------------------
# (b) ledger_path / append_measurement / read_measurements / latest_measurement
# ---------------------------------------------------------------------------


class TestLedgerReadWrite:
    def test_ledger_path_is_under_metrics_dir(self, tmp_path: Path) -> None:
        assert ledger_path(tmp_path) == tmp_path / "metrics.jsonl"

    def test_append_then_read_round_trips(self, tmp_path: Path) -> None:
        path = ledger_path(tmp_path)
        append_measurement(path, _record("bench", 1.0, 100.0))
        append_measurement(path, _record("bench", 2.0, 200.0))

        records = read_measurements(path)
        assert [(r.value, r.ts) for r in records] == [(1.0, 100.0), (2.0, 200.0)]

    def test_append_creates_parent_dir(self, tmp_path: Path) -> None:
        path = ledger_path(tmp_path / "nested" / "metrics")
        append_measurement(path, _record("bench", 1.0, 100.0))
        assert path.exists()

    def test_read_absent_ledger_is_empty(self, tmp_path: Path) -> None:
        assert read_measurements(ledger_path(tmp_path)) == []

    def test_read_filters_by_check(self, tmp_path: Path) -> None:
        path = ledger_path(tmp_path)
        append_measurement(path, _record("a", 1.0, 1.0))
        append_measurement(path, _record("b", 2.0, 2.0))
        append_measurement(path, _record("a", 3.0, 3.0))

        records = read_measurements(path, check="a")
        assert [r.value for r in records] == [1.0, 3.0]

    def test_malformed_line_is_skipped(self, tmp_path: Path) -> None:
        path = ledger_path(tmp_path)
        append_measurement(path, _record("a", 1.0, 1.0))
        with path.open("a") as fh:
            fh.write("not json\n")
        append_measurement(path, _record("a", 2.0, 2.0))

        records = read_measurements(path)
        assert [r.value for r in records] == [1.0, 2.0]

    def test_unreadable_ledger_is_skipped(self, tmp_path: Path) -> None:
        path = ledger_path(tmp_path)
        path.mkdir()  # a directory named metrics.jsonl -> read_text() raises

        assert read_measurements(path) == []

    def test_latest_measurement_is_the_last_record(self, tmp_path: Path) -> None:
        path = ledger_path(tmp_path)
        append_measurement(path, _record("bench", 1.0, 1.0))
        append_measurement(path, _record("bench", 2.0, 2.0))
        append_measurement(path, _record("bench", 3.0, 3.0))

        latest = latest_measurement(path, "bench")
        assert latest is not None
        assert latest.value == 3.0

    def test_latest_measurement_none_when_no_history(self, tmp_path: Path) -> None:
        assert latest_measurement(ledger_path(tmp_path), "bench") is None

    def test_latest_measurement_scoped_to_check_name(self, tmp_path: Path) -> None:
        path = ledger_path(tmp_path)
        append_measurement(path, _record("a", 1.0, 1.0))
        append_measurement(path, _record("b", 99.0, 2.0))

        latest = latest_measurement(path, "a")
        assert latest is not None
        assert latest.value == 1.0

    def test_latest_measurement_returns_a_rejected_record_too(self, tmp_path: Path) -> None:
        # `latest_measurement` is read-side only (any outcome) — it is NEVER
        # what the Verifier judges a fresh value against; that is
        # `latest_accepted_measurement` below.
        path = ledger_path(tmp_path)
        append_measurement(path, _record("bench", 100.0, 1.0, passed=True))
        append_measurement(path, _record("bench", 200.0, 2.0, passed=False))

        latest = latest_measurement(path, "bench")
        assert latest is not None
        assert latest.value == 200.0


class TestLatestAcceptedMeasurement:
    def test_skips_a_trailing_rejected_record(self, tmp_path: Path) -> None:
        # The core of the fix: a rejected measurement must never be selected
        # as the baseline for the next judgment.
        path = ledger_path(tmp_path)
        append_measurement(path, _record("bench", 100.0, 1.0, passed=True))
        append_measurement(path, _record("bench", 200.0, 2.0, passed=False))

        baseline = latest_accepted_measurement(path, "bench")
        assert baseline is not None
        assert baseline.value == 100.0

    def test_returns_the_most_recent_of_several_accepted_records(
        self, tmp_path: Path
    ) -> None:
        path = ledger_path(tmp_path)
        append_measurement(path, _record("bench", 100.0, 1.0, passed=True))
        append_measurement(path, _record("bench", 105.0, 2.0, passed=True))

        baseline = latest_accepted_measurement(path, "bench")
        assert baseline is not None
        assert baseline.value == 105.0

    def test_none_when_every_record_was_rejected(self, tmp_path: Path) -> None:
        path = ledger_path(tmp_path)
        append_measurement(path, _record("bench", 200.0, 1.0, passed=False))
        append_measurement(path, _record("bench", 300.0, 2.0, passed=False))

        assert latest_accepted_measurement(path, "bench") is None

    def test_none_when_no_history(self, tmp_path: Path) -> None:
        assert latest_accepted_measurement(ledger_path(tmp_path), "bench") is None

    def test_scoped_to_check_name(self, tmp_path: Path) -> None:
        path = ledger_path(tmp_path)
        append_measurement(path, _record("a", 1.0, 1.0, passed=True))
        append_measurement(path, _record("b", 99.0, 2.0, passed=True))

        baseline = latest_accepted_measurement(path, "a")
        assert baseline is not None
        assert baseline.value == 1.0


# ---------------------------------------------------------------------------
# (c) within_tolerance — the pure comparison rule
# ---------------------------------------------------------------------------


class TestWithinTolerance:
    def test_lower_is_better_at_exact_tolerance_boundary_passes(self) -> None:
        assert within_tolerance(105.0, 100.0, "lower_is_better", 5.0) is True

    def test_lower_is_better_just_past_boundary_fails(self) -> None:
        assert within_tolerance(105.01, 100.0, "lower_is_better", 5.0) is False

    def test_lower_is_better_improvement_always_passes(self) -> None:
        assert within_tolerance(50.0, 100.0, "lower_is_better", 0.0) is True

    def test_higher_is_better_at_exact_tolerance_boundary_passes(self) -> None:
        assert within_tolerance(95.0, 100.0, "higher_is_better", 5.0) is True

    def test_higher_is_better_just_past_boundary_fails(self) -> None:
        assert within_tolerance(94.99, 100.0, "higher_is_better", 5.0) is False

    def test_higher_is_better_improvement_always_passes(self) -> None:
        assert within_tolerance(150.0, 100.0, "higher_is_better", 0.0) is True

    def test_zero_tolerance_requires_exact_match_or_better(self) -> None:
        assert within_tolerance(100.0, 100.0, "lower_is_better", 0.0) is True
        assert within_tolerance(100.01, 100.0, "lower_is_better", 0.0) is False


# ---------------------------------------------------------------------------
# (d) metric_series — the per-check time series with delta + trend
# ---------------------------------------------------------------------------


class TestMetricSeries:
    def test_empty_ledger_yields_empty_series(self, tmp_path: Path) -> None:
        assert metric_series(ledger_path(tmp_path)) == {}

    def test_first_point_has_no_delta(self, tmp_path: Path) -> None:
        path = ledger_path(tmp_path)
        append_measurement(path, _record("bench", 10.0, 1.0))

        [point] = metric_series(path)["bench"]
        assert point == MetricPoint(
            ts=1.0, value=10.0, run="r", delta=None, trend="n/a", passed=True
        )

    def test_delta_and_trend_up(self, tmp_path: Path) -> None:
        path = ledger_path(tmp_path)
        append_measurement(path, _record("bench", 10.0, 1.0))
        append_measurement(path, _record("bench", 15.0, 2.0))

        points = metric_series(path)["bench"]
        assert points[1].delta == 5.0
        assert points[1].trend == "up"

    def test_delta_and_trend_down(self, tmp_path: Path) -> None:
        path = ledger_path(tmp_path)
        append_measurement(path, _record("bench", 10.0, 1.0))
        append_measurement(path, _record("bench", 4.0, 2.0))

        points = metric_series(path)["bench"]
        assert points[1].delta == -6.0
        assert points[1].trend == "down"

    def test_delta_and_trend_flat(self, tmp_path: Path) -> None:
        path = ledger_path(tmp_path)
        append_measurement(path, _record("bench", 10.0, 1.0))
        append_measurement(path, _record("bench", 10.0, 2.0))

        points = metric_series(path)["bench"]
        assert points[1].delta == 0.0
        assert points[1].trend == "flat"

    def test_passed_mirrors_the_record(self, tmp_path: Path) -> None:
        path = ledger_path(tmp_path)
        append_measurement(path, _record("bench", 10.0, 1.0, passed=True))
        append_measurement(path, _record("bench", 20.0, 2.0, passed=False))

        points = metric_series(path)["bench"]
        assert [p.passed for p in points] == [True, False]

    def test_groups_by_check_name(self, tmp_path: Path) -> None:
        path = ledger_path(tmp_path)
        append_measurement(path, _record("a", 1.0, 1.0))
        append_measurement(path, _record("b", 2.0, 2.0))

        assert set(metric_series(path)) == {"a", "b"}

    def test_check_filter_scopes_to_one_series(self, tmp_path: Path) -> None:
        path = ledger_path(tmp_path)
        append_measurement(path, _record("a", 1.0, 1.0))
        append_measurement(path, _record("b", 2.0, 2.0))

        assert set(metric_series(path, check="a")) == {"a"}


# ---------------------------------------------------------------------------
# (e) CLI — `alc metrics [--check NAME] [--json]`
# ---------------------------------------------------------------------------


def _ns(**overrides) -> argparse.Namespace:
    defaults = {"check": None, "json": False}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestMetricsCli:
    def test_no_history_prints_a_clear_message(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)
        assert cmd_metrics(_ns()) == 0
        assert "No metric history yet" in capsys.readouterr().out

    def test_never_writes_anything(self, operator_layer: Path, monkeypatch) -> None:
        monkeypatch.chdir(operator_layer.parent)
        before = sorted(p.relative_to(operator_layer.parent) for p in operator_layer.rglob("*"))
        assert cmd_metrics(_ns()) == 0
        after = sorted(p.relative_to(operator_layer.parent) for p in operator_layer.rglob("*"))
        assert before == after

    def test_human_output_shows_value_delta_and_trend(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        path = ledger_path(operator_layer.parent / ".alc" / "metrics")
        append_measurement(path, _record("bundle-size", 100.0, 1.0, run="ship"))
        append_measurement(path, _record("bundle-size", 110.0, 2.0, run="ship"))
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_metrics(_ns()) == 0
        out = capsys.readouterr().out

        assert "bundle-size:" in out
        assert "first measurement" in out
        assert "delta=+10" in out
        assert "trend=up" in out
        assert "run=ship" in out
        assert "status=accepted" in out  # the second (accepted) point

    def test_human_output_flags_a_rejected_point(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        path = ledger_path(operator_layer.parent / ".alc" / "metrics")
        append_measurement(path, _record("bundle-size", 100.0, 1.0, run="ship", passed=True))
        append_measurement(path, _record("bundle-size", 200.0, 2.0, run="ship", passed=False))
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_metrics(_ns()) == 0
        out = capsys.readouterr().out

        assert "status=REJECTED" in out

    def test_check_filter_only_shows_that_check(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        path = ledger_path(operator_layer.parent / ".alc" / "metrics")
        append_measurement(path, _record("a", 1.0, 1.0))
        append_measurement(path, _record("b", 2.0, 2.0))
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_metrics(_ns(check="a")) == 0
        out = capsys.readouterr().out

        assert "a:" in out
        assert "b:" not in out

    def test_json_output_matches_metric_series(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        path = ledger_path(operator_layer.parent / ".alc" / "metrics")
        append_measurement(path, _record("bench", 10.0, 1.0, run="r"))
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_metrics(_ns(json=True)) == 0
        data = json.loads(capsys.readouterr().out)

        assert data == {
            "bench": [
                {
                    "ts": 1.0,
                    "value": 10.0,
                    "run": "r",
                    "delta": None,
                    "trend": "n/a",
                    "passed": True,
                }
            ]
        }
