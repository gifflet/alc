# test_metric_checks.py — Hermetic tests for metric checks:
# `metric` checks (the third form of Check), the Verifier's judgment against
# the metric ledger, and the Policy Gate rule that `direction` is required
# whenever `metric` is declared.
#
# (a) Check.metric/direction/tolerance_pct front-matter + validation.
# (b) Policy Gate rule 14: metric requires direction.
# (c) Verifier: parses stdout, judges against the ledger, records the value.
# (d) runner.py wiring: metrics_dir + run label reach the Verifier.
# (e) A regression must actually fail a run with the DEFAULT repair budget,
#     and must never become the next run's baseline — driven through
#     execute_mandate (the real path), not by calling Verifier internals.
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from alc.engine import Capabilities, EngineRequest, EngineResult
from alc.intake import load_blueprint
from alc.metrics import latest_accepted_measurement, ledger_path, read_measurements
from alc.models import Blueprint, Check, Manifest
from alc.policy import lint
from alc.runner import execute_mandate
from alc.verifier import Verifier

_MINIMAL_MANIFEST = Manifest(
    version=1,
    default_engine="mock",
    compute_tiers={"standard": {"mock": "mock-small"}},
    engines={"mock": {"type": "mock"}},
)


# ---------------------------------------------------------------------------
# (a) Check.metric front-matter + validation
# ---------------------------------------------------------------------------


class TestCheckMetricField:
    def test_default_is_none(self) -> None:
        check = Check(name="t", command=["true"])
        assert check.metric is None
        assert check.direction is None
        assert check.tolerance_pct == 0.0

    def test_metric_as_argv_is_valid(self) -> None:
        check = Check(name="bench", metric=["scripts/bench.py"], direction="lower_is_better")
        assert check.metric == ["scripts/bench.py"]

    def test_metric_as_shell_string_is_valid(self) -> None:
        check = Check(name="bench", metric="cat size.txt", direction="lower_is_better")
        assert check.metric == "cat size.txt"

    def test_metric_and_command_together_raises(self) -> None:
        with pytest.raises(ValidationError, match="exactly one"):
            Check(name="t", command=["true"], metric=["bench.py"], direction="lower_is_better")

    def test_metric_and_shell_together_raises(self) -> None:
        with pytest.raises(ValidationError, match="exactly one"):
            Check(name="t", shell="true", metric=["bench.py"], direction="lower_is_better")

    def test_no_form_at_all_still_raises(self) -> None:
        with pytest.raises(ValidationError, match="exactly one"):
            Check(name="t")

    def test_metric_without_direction_is_still_a_valid_model(self) -> None:
        # T1: "direction required when metric is set" is a POLICY GATE rule
        # (error), deliberately NOT a pydantic validator — see
        # TestPolicyMetricRequiresDirection below for where it IS enforced.
        check = Check(name="bench", metric=["bench.py"])
        assert check.direction is None

    def test_negative_tolerance_pct_raises(self) -> None:
        with pytest.raises(ValidationError, match="tolerance_pct"):
            Check(
                name="bench",
                metric=["bench.py"],
                direction="lower_is_better",
                tolerance_pct=-1,
            )

    def test_tolerance_pct_defaults_to_zero(self) -> None:
        check = Check(name="bench", metric=["bench.py"], direction="lower_is_better")
        assert check.tolerance_pct == 0.0

    def test_front_matter_round_trip(self, tmp_path: Path) -> None:
        blueprints_dir = tmp_path / "blueprints"
        blueprints_dir.mkdir()
        (blueprints_dir / "perf.md").write_text(
            """\
---
name: perf
purpose: A perf blueprint.
compute_tier: standard
checks:
  - name: bundle-size
    metric: ["scripts/bundle_size.py"]
    direction: lower_is_better
    tolerance_pct: 5.0
---
# Workflow
Do the task.
"""
        )
        bp = load_blueprint(blueprints_dir, "perf")
        check = bp.checks[0]
        assert check.metric == ["scripts/bundle_size.py"]
        assert check.direction == "lower_is_better"
        assert check.tolerance_pct == 5.0


# ---------------------------------------------------------------------------
# (b) Policy Gate — metric requires direction
# ---------------------------------------------------------------------------


class TestPolicyMetricRequiresDirection:
    def test_metric_without_direction_is_an_error(self) -> None:
        bp = Blueprint(
            name="perf",
            purpose="p",
            workflow="w",
            checks=[Check(name="bundle-size", metric=["bench.py"])],
        )
        violations = lint(_MINIMAL_MANIFEST, [bp])
        matching = [v for v in violations if v.rule == "metric-requires-direction"]
        assert len(matching) == 1
        assert matching[0].severity == "error"
        assert "bundle-size" in matching[0].message

    def test_metric_with_direction_is_clean(self) -> None:
        bp = Blueprint(
            name="perf",
            purpose="p",
            workflow="w",
            checks=[Check(name="bundle-size", metric=["bench.py"], direction="lower_is_better")],
        )
        violations = lint(_MINIMAL_MANIFEST, [bp])
        assert [v for v in violations if v.rule == "metric-requires-direction"] == []

    def test_non_metric_checks_are_unaffected(self) -> None:
        bp = Blueprint(
            name="chore",
            purpose="p",
            workflow="w",
            checks=[Check(name="smoke", command=["true"])],
        )
        violations = lint(_MINIMAL_MANIFEST, [bp])
        assert [v for v in violations if v.rule == "metric-requires-direction"] == []


# ---------------------------------------------------------------------------
# (c) Verifier — metric judgment
# ---------------------------------------------------------------------------


def _metric_check(
    name: str = "bench",
    *,
    shell: str,
    direction: str = "lower_is_better",
    tolerance_pct: float = 0.0,
    flaky: int = 0,
) -> Check:
    return Check(
        name=name, metric=shell, direction=direction, tolerance_pct=tolerance_pct, flaky=flaky
    )


class TestVerifierMetricJudgment:
    def test_first_measurement_always_passes_and_is_recorded(self, tmp_path: Path) -> None:
        metrics_dir = tmp_path / "metrics"
        [result] = Verifier(timeout_s=30, metrics_dir=metrics_dir, run_id="r1").run(
            [_metric_check(shell="echo 100")], tmp_path
        )
        assert result.passed is True
        assert "first measurement" in result.output

        records = read_measurements(ledger_path(metrics_dir))
        assert len(records) == 1
        assert records[0].check == "bench"
        assert records[0].value == 100.0
        assert records[0].run == "r1"

    def test_an_unchanged_re_measurement_within_one_run_is_not_re_recorded(
        self, tmp_path: Path
    ) -> None:
        """One run measures per attempt plus a final re-verify; identical numbers
        would flood the series, so only a value that MOVED is recorded again."""
        metrics_dir = tmp_path / "metrics"
        verifier = Verifier(timeout_s=30, metrics_dir=metrics_dir, run_id="r1")
        check = _metric_check(shell="echo 100")

        verifier.run([check], tmp_path)
        verifier.run([check], tmp_path)
        verifier.run([check], tmp_path)

        assert len(read_measurements(ledger_path(metrics_dir))) == 1

    def test_a_value_that_moved_within_one_run_is_recorded(self, tmp_path: Path) -> None:
        """A repair that actually changes the number must still land in the series."""
        metrics_dir = tmp_path / "metrics"
        verifier = Verifier(timeout_s=30, metrics_dir=metrics_dir, run_id="r1")

        verifier.run([_metric_check(shell="echo 100")], tmp_path)
        verifier.run([_metric_check(shell="echo 90")], tmp_path)

        assert [r.value for r in read_measurements(ledger_path(metrics_dir))] == [100.0, 90.0]

    # NOTE: each scenario below that spans more than one measurement uses a
    # SEPARATE Verifier instance per measurement — a fresh Verifier IS a
    # fresh run (runner.py/flow.py construct exactly one per mandate/stage;
    # see TestVerifierBaselineFrozenPerRun and
    # TestRegressionSurvivesRepairAndDoesNotBecomeBaseline below for what
    # happens across ATTEMPTS of the SAME run, which is a different thing).

    def test_lower_is_better_within_tolerance_passes(self, tmp_path: Path) -> None:
        metrics_dir = tmp_path / "metrics"
        Verifier(timeout_s=30, metrics_dir=metrics_dir, run_id="r1").run(
            [_metric_check(shell="echo 100", tolerance_pct=5.0)], tmp_path
        )

        [result] = Verifier(timeout_s=30, metrics_dir=metrics_dir, run_id="r2").run(
            [_metric_check(shell="echo 104", tolerance_pct=5.0)], tmp_path
        )
        assert result.passed is True  # +4% <= 5% tolerance

    def test_lower_is_better_beyond_tolerance_fails(self, tmp_path: Path) -> None:
        metrics_dir = tmp_path / "metrics"
        Verifier(timeout_s=30, metrics_dir=metrics_dir, run_id="r1").run(
            [_metric_check(shell="echo 100", tolerance_pct=5.0)], tmp_path
        )

        [result] = Verifier(timeout_s=30, metrics_dir=metrics_dir, run_id="r2").run(
            [_metric_check(shell="echo 110", tolerance_pct=5.0)], tmp_path
        )
        assert result.passed is False  # +10% > 5% tolerance
        assert "REGRESSION" in result.output

    def test_higher_is_better_within_tolerance_passes(self, tmp_path: Path) -> None:
        metrics_dir = tmp_path / "metrics"
        Verifier(timeout_s=30, metrics_dir=metrics_dir, run_id="r1").run(
            [_metric_check(shell="echo 100", direction="higher_is_better", tolerance_pct=5.0)],
            tmp_path,
        )

        [result] = Verifier(timeout_s=30, metrics_dir=metrics_dir, run_id="r2").run(
            [_metric_check(shell="echo 96", direction="higher_is_better", tolerance_pct=5.0)],
            tmp_path,
        )
        assert result.passed is True  # -4% within 5% tolerance

    def test_higher_is_better_beyond_tolerance_fails(self, tmp_path: Path) -> None:
        metrics_dir = tmp_path / "metrics"
        Verifier(timeout_s=30, metrics_dir=metrics_dir, run_id="r1").run(
            [_metric_check(shell="echo 100", direction="higher_is_better", tolerance_pct=5.0)],
            tmp_path,
        )

        [result] = Verifier(timeout_s=30, metrics_dir=metrics_dir, run_id="r2").run(
            [_metric_check(shell="echo 90", direction="higher_is_better", tolerance_pct=5.0)],
            tmp_path,
        )
        assert result.passed is False  # -10% beyond 5% tolerance

    def test_a_rejected_measurement_is_still_recorded_but_not_as_a_future_baseline(
        self, tmp_path: Path
    ) -> None:
        # Corrected design (this value's own coordinator review): every
        # measurement is still recorded — an honest history — but only an
        # ACCEPTED one may ever become a future baseline. A run's own
        # rejected value must never move the goalpost for the NEXT run.
        metrics_dir = tmp_path / "metrics"
        Verifier(timeout_s=30, metrics_dir=metrics_dir, run_id="r1").run(
            [_metric_check(shell="echo 100", tolerance_pct=5.0)], tmp_path
        )

        [regressed] = Verifier(timeout_s=30, metrics_dir=metrics_dir, run_id="r2").run(
            [_metric_check(shell="echo 200", tolerance_pct=5.0)], tmp_path
        )
        assert regressed.passed is False

        records = read_measurements(ledger_path(metrics_dir), check="bench")
        assert [(r.value, r.passed) for r in records] == [(100.0, True), (200.0, False)]

        # The next measurement is STILL compared against the original 100
        # baseline, not the rejected 200 — 205 is a real regression too.
        [result] = Verifier(timeout_s=30, metrics_dir=metrics_dir, run_id="r3").run(
            [_metric_check(shell="echo 205", tolerance_pct=5.0)], tmp_path
        )
        assert result.passed is False

    def test_baseline_is_frozen_for_the_lifetime_of_one_verifier_instance(
        self, tmp_path: Path
    ) -> None:
        # Direct repro of the reported defect at the Verifier level: within
        # ONE instance (== one run — see runner.py/flow.py, which construct
        # exactly one Verifier per run), a value THIS instance just recorded
        # must not become the baseline for its OWN next attempt, or a
        # repair-loop re-verify launders a regression into a pass.
        metrics_dir = tmp_path / "metrics"
        Verifier(timeout_s=30, metrics_dir=metrics_dir, run_id="r1").run(
            [_metric_check(shell="echo 100", tolerance_pct=10.0)], tmp_path
        )

        v = Verifier(timeout_s=30, metrics_dir=metrics_dir, run_id="r2")
        check = _metric_check(shell="echo 200", tolerance_pct=10.0)
        [first_attempt] = v.run([check], tmp_path)
        [second_attempt] = v.run([check], tmp_path)  # e.g. the repair-budget-exhausted re-verify

        assert first_attempt.passed is False
        assert second_attempt.passed is False  # NOT laundered into a pass

    def test_non_numeric_stdout_fails_clearly_not_a_crash(self, tmp_path: Path) -> None:
        [result] = Verifier(timeout_s=30, metrics_dir=tmp_path / "metrics", run_id="r").run(
            [_metric_check(shell="echo not-a-number")], tmp_path
        )
        assert result.passed is False
        assert "non-numeric" in result.output

    def test_nonzero_exit_fails_without_recording(self, tmp_path: Path) -> None:
        metrics_dir = tmp_path / "metrics"
        [result] = Verifier(timeout_s=30, metrics_dir=metrics_dir, run_id="r").run(
            [_metric_check(shell="echo 100 1>&2; exit 1")], tmp_path
        )
        assert result.passed is False
        assert read_measurements(ledger_path(metrics_dir)) == []

    def test_missing_binary_fails_without_crashing(self, tmp_path: Path) -> None:
        check = Check(name="bench", metric=["no-such-binary-xyz"], direction="lower_is_better")
        [result] = Verifier(timeout_s=30, metrics_dir=tmp_path / "metrics", run_id="r").run(
            [check], tmp_path
        )
        assert result.passed is False
        assert result.exit_code is None

    def test_no_direction_fails_defensively_not_a_crash(self, tmp_path: Path) -> None:
        # Bypasses the Policy Gate on purpose (the pydantic model allows a
        # metric with no direction — see TestCheckMetricField) to prove the
        # Verifier degrades gracefully rather than raising.
        check = Check(name="bench", metric="echo 100")
        [result] = Verifier(timeout_s=30, metrics_dir=tmp_path / "metrics").run([check], tmp_path)
        assert result.passed is False
        assert "direction" in result.output

    def test_no_metrics_dir_configured_passes_without_recording(self, tmp_path: Path) -> None:
        [result] = Verifier(timeout_s=30).run([_metric_check(shell="echo 100")], tmp_path)
        assert result.passed is True
        assert "not recorded" in result.output

    def test_flaky_is_not_applied_to_metric_checks(self, tmp_path: Path) -> None:
        metrics_dir = tmp_path / "metrics"
        marker = tmp_path / "calls.txt"
        Verifier(timeout_s=30, metrics_dir=metrics_dir, run_id="r1").run(
            [_metric_check(shell="echo 100")], tmp_path
        )  # baseline, a separate prior run

        check = _metric_check(shell=f"echo x >> {marker}; echo 200", flaky=3)
        [result] = Verifier(timeout_s=30, metrics_dir=metrics_dir, run_id="r2").run(
            [check], tmp_path
        )

        assert result.passed is False  # a regression vs the 100 baseline
        assert len(marker.read_text().splitlines()) == 1  # ran once, no flaky rerun

    def test_measured_value_is_visible_in_check_result_output(self, tmp_path: Path) -> None:
        [result] = Verifier(timeout_s=30, metrics_dir=tmp_path / "metrics", run_id="r").run(
            [_metric_check(shell="echo 42.5")], tmp_path
        )
        assert "42.5" in result.output

    def test_duration_and_exit_code_are_still_populated(self, tmp_path: Path) -> None:
        [result] = Verifier(timeout_s=30, metrics_dir=tmp_path / "metrics", run_id="r").run(
            [_metric_check(shell="echo 1")], tmp_path
        )
        assert result.duration_s >= 0.0
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# (d) runner.py wiring — metrics_dir + run label reach the Verifier
# ---------------------------------------------------------------------------


class _NoopEngine:
    name = "mock"

    def capabilities(self) -> Capabilities:
        return Capabilities()

    def health_check(self) -> bool:
        return True

    def run(self, request: EngineRequest) -> EngineResult:
        return EngineResult(ok=True, output_text="[mock] did nothing")


class TestExecuteMandateMetricsIntegration:
    def test_metric_check_is_recorded_under_the_project_metrics_dir(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: _NoopEngine())

        operator_layer = tmp_path / ".alc"
        operator_layer.mkdir()
        bp = Blueprint(
            name="perf",
            purpose="p",
            workflow="# w",
            checks=[Check(name="bundle-size", metric="echo 1000", direction="lower_is_better")],
        )

        report = execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=bp,
            directive="# test\ndo it",
            engine_override="mock",
            workdir=tmp_path,
            operator_layer=operator_layer,
        )

        assert report.success is True
        records = read_measurements(
            ledger_path(operator_layer.parent / _MINIMAL_MANIFEST.metrics_dir)
        )
        assert len(records) == 1
        assert records[0].check == "bundle-size"
        assert records[0].run == "perf"

    def test_no_operator_layer_degrades_to_not_recorded_never_crashes(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: _NoopEngine())

        bp = Blueprint(
            name="perf",
            purpose="p",
            workflow="# w",
            checks=[Check(name="bundle-size", metric="echo 1000", direction="lower_is_better")],
        )

        report = execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=bp,
            directive="# test\ndo it",
            engine_override="mock",
            workdir=tmp_path,
            operator_layer=None,
        )

        assert report.success is True  # no history + no metrics_dir -> still passes


# ---------------------------------------------------------------------------
# (e) A regression must FAIL a run — with the default repair budget, not only
#     max_repairs: 0 — and must never become the next run's baseline.
#     Reported by the coordinator's manual `alc run` verification: the
#     Verifier previously read the ledger fresh on every attempt, so a
#     repair-loop re-verify measured the regression again, saw its OWN just-
#     written value as the "baseline", and passed. Reproduced here through
#     execute_mandate (one Verifier per run, exactly as runner.py builds it)
#     with the Blueprint's max_repairs left unset (default budget = 3).
# ---------------------------------------------------------------------------


class TestRegressionSurvivesRepairAndDoesNotBecomeBaseline:
    def _run(self, tmp_path: Path, operator_layer: Path, *, metric_shell: str):
        bp = Blueprint(
            name="perf",
            purpose="p",
            workflow="# w",
            checks=[
                Check(
                    name="bundle-size",
                    metric=metric_shell,
                    direction="lower_is_better",
                    tolerance_pct=10.0,
                )
            ],
        )
        return execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=bp,
            directive="# test\ndo it",
            engine_override="mock",
            workdir=tmp_path,
            operator_layer=operator_layer,
        )

    def test_regression_fails_with_the_default_repair_budget(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: _NoopEngine())
        operator_layer = tmp_path / ".alc"
        operator_layer.mkdir()

        first = self._run(tmp_path, operator_layer, metric_shell="echo 100")
        assert first.success is True  # baseline

        # +100% against a 10% tolerance. The Blueprint sets no max_repairs, so
        # the AssuranceLoop uses its default (3 repairs = 4 engine attempts)
        # plus the post-budget re-verify — every one of those re-measures the
        # SAME "echo 200" and must be judged against the SAME frozen 100
        # baseline every time, never each other's just-written value.
        second = self._run(tmp_path, operator_layer, metric_shell="echo 200")
        assert second.success is False
        assert "bundle-size" in second.attempts[-1].failed_checks

    def test_a_regression_that_failed_run_n_does_not_become_run_n_plus_1s_baseline(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: _NoopEngine())
        operator_layer = tmp_path / ".alc"
        operator_layer.mkdir()

        self._run(tmp_path, operator_layer, metric_shell="echo 100")  # run 1: baseline
        regressed = self._run(tmp_path, operator_layer, metric_shell="echo 200")  # run 2
        assert regressed.success is False

        # Run 3 measures 150: a real regression against the ORIGINAL 100
        # baseline (150 > 110, the 10%-tolerance ceiling) — but if run 2's
        # REJECTED 200 had wrongly become the baseline, 150 would sit
        # comfortably inside ITS tolerance band (<= 220) and pass. Asserting
        # failure here is exactly what proves the 200 never became the
        # baseline.
        third = self._run(tmp_path, operator_layer, metric_shell="echo 150")
        assert third.success is False

    def test_a_failing_run_does_not_corrupt_the_series_for_the_next_run(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: _NoopEngine())
        operator_layer = tmp_path / ".alc"
        operator_layer.mkdir()

        self._run(tmp_path, operator_layer, metric_shell="echo 100")  # run 1: baseline
        self._run(tmp_path, operator_layer, metric_shell="echo 200")  # run 2: rejected

        path = ledger_path(operator_layer.parent / _MINIMAL_MANIFEST.metrics_dir)

        # The baseline the NEXT run would judge against is untouched by the
        # failing run.
        baseline = latest_accepted_measurement(path, "bundle-size")
        assert baseline is not None
        assert baseline.value == 100.0

        # The rejected run is still honestly visible in the ledger, not
        # dropped from history.
        all_records = read_measurements(path, check="bundle-size")
        assert any(r.value == 200.0 and r.passed is False for r in all_records)

        # A follow-up run within tolerance of the UNCORRUPTED 100 baseline
        # succeeds, proving the series is still usable going forward.
        recovered = self._run(tmp_path, operator_layer, metric_shell="echo 105")
        assert recovered.success is True
