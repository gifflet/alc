# test_replenish_regression.py — Hermetic tests for roadmap-phase-5.md T5: the
# `regression` replenish kind (models.Replenish + loop.run_replenish) — the
# mechanism that closes the Grower's loop over a measured regression.
#
# Design decision under test (see loop.py's run_replenish docstring for the
# full rationale): a check's newest not-yet-seen metric-ledger record decides
# its current state. A record can only be `passed=False` (the Verifier's own
# tolerance judgment, made using the real Check's direction/tolerance_pct at
# measurement time — never re-derived here) when a real baseline already
# existed to fail against, so a check with a single measurement can never
# regress. "Since last cycle" is tracked via a per-check record-count cursor
# persisted in LoopState.metric_cursor, advanced past every record considered
# (regressed or not) so the SAME ledger entry is never re-flagged.
#
# Uses the conftest `operator_layer` fixture (ships a `ship` flow: plan ->
# build, both single 'true' checks — succeeds under the mock engine).
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from alc import loop as loop_mod
from alc.intake import load_loop, load_manifest
from alc.loop import loops_dir, run_cycle
from alc.metrics import append_measurement, ledger_path
from alc.models import LoopDefinition, LoopState, MetricRecord, QueueTask, Replenish
from alc.policy import validate_loop


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_loop(operator_layer: Path, name: str, body: str) -> None:
    loops = operator_layer / "loops"
    loops.mkdir(exist_ok=True)
    (loops / f"{name}.yaml").write_text(body)


def _write_regression_loop(
    operator_layer: Path,
    ref: str = "ship",
    task: str = "Investigate and fix:",
    concurrency: int | None = None,
) -> None:
    body = (
        f"name: heal\nreplenish:\n  kind: regression\n  ref: {ref}\n  task: \"{task}\"\n"
        "stop:\n  max_cycles: 20\n"
    )
    if concurrency is not None:
        body += f"drain:\n  concurrency: {concurrency}\n"
    _write_loop(operator_layer, "heal", body)


def _seed_measurement(
    operator_layer: Path,
    check: str,
    value: float,
    ts: float,
    run: str = "bench-run",
    passed: bool = True,
) -> None:
    manifest = load_manifest(operator_layer)
    path = ledger_path(operator_layer.parent / manifest.metrics_dir)
    append_measurement(path, MetricRecord(check=check, value=value, ts=ts, run=run, passed=passed))


def _pending_queue_files(operator_layer: Path) -> list[Path]:
    manifest = load_manifest(operator_layer)
    queue_dir = operator_layer.parent / manifest.queue_dir
    return sorted(queue_dir.glob("*.yaml")) if queue_dir.is_dir() else []


# ---------------------------------------------------------------------------
# Replenish model — the 'regression' kind requires a ref (the target flow)
# ---------------------------------------------------------------------------


class TestReplenishRegressionModel:
    def test_regression_kind_requires_ref(self) -> None:
        with pytest.raises(ValidationError, match="ref"):
            Replenish(kind="regression", ref=None, task="Fix:")

    def test_regression_kind_with_ref_is_valid(self) -> None:
        replenish = Replenish(kind="regression", ref="ship", task="Fix:")
        assert replenish.kind == "regression"
        assert replenish.ref == "ship"


# ---------------------------------------------------------------------------
# Policy Gate — a regression-kind ref must name an existing flow
# ---------------------------------------------------------------------------


class TestReplenishRegressionValidation:
    def test_missing_flow_ref_yields_error_violation(self, operator_layer: Path) -> None:
        loop_def = LoopDefinition.model_validate(
            {
                "name": "bad-loop",
                "replenish": {"kind": "regression", "ref": "nonexistent", "task": "fix:"},
                "stop": {"max_cycles": 5},
            }
        )
        manifest = load_manifest(operator_layer)
        violations = validate_loop(manifest, operator_layer, loop_def)
        error_rules = [v.rule for v in violations if v.severity == "error"]
        assert "loop-replenish-flow-exists" in error_rules, (
            f"Expected 'loop-replenish-flow-exists' error, got violations: {violations}"
        )

    def test_existing_flow_ref_no_violation(self, operator_layer: Path) -> None:
        loop_def = LoopDefinition.model_validate(
            {
                "name": "ok-loop",
                "replenish": {"kind": "regression", "ref": "ship", "task": "fix:"},
                "stop": {"max_cycles": 5},
            }
        )
        manifest = load_manifest(operator_layer)
        violations = validate_loop(manifest, operator_layer, loop_def)
        error_rules = [v.rule for v in violations if v.severity == "error"]
        assert "loop-replenish-flow-exists" not in error_rules


# ---------------------------------------------------------------------------
# LoopState.metric_cursor — additive field, byte-identical to old persisted state
# ---------------------------------------------------------------------------


class TestLoopStateMetricCursor:
    def test_default_is_empty(self) -> None:
        assert LoopState(name="heal").metric_cursor == {}

    def test_old_persisted_json_without_the_field_still_loads(self) -> None:
        old_json = '{"name": "heal", "status": "running", "cycle": 3}'
        state = LoopState.model_validate_json(old_json)
        assert state.metric_cursor == {}
        assert state.cycle == 3


# ---------------------------------------------------------------------------
# run_replenish — dispatch
# ---------------------------------------------------------------------------


class TestReplenishRegressionDispatch:
    def test_prints_header(self, operator_layer: Path, capsys) -> None:
        _write_regression_loop(operator_layer)
        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "heal")

        loop_mod.run_replenish(manifest, operator_layer, loop_def, engine_override="mock")

        err = capsys.readouterr().err
        assert "▶ replenish — regression:ship" in err

    def test_no_metric_ledger_is_a_no_op(self, operator_layer: Path) -> None:
        _write_regression_loop(operator_layer)
        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "heal")

        enqueued, delta, ok = loop_mod.run_replenish(
            manifest, operator_layer, loop_def, engine_override="mock"
        )

        assert enqueued == 0
        assert delta == {"engine_calls": 0.0, "usd": 0.0, "tokens": 0.0}
        assert ok is True
        assert _pending_queue_files(operator_layer) == []

    def test_single_measurement_cannot_regress(self, operator_layer: Path) -> None:
        # The FIRST-ever measurement of a check always records passed=True (no
        # baseline yet to fail against — see verifier._judge_metric), so a
        # check with exactly one point can never trip a regression.
        _seed_measurement(operator_layer, "bench", value=100.0, ts=1.0, passed=True)
        _write_regression_loop(operator_layer)
        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "heal")

        enqueued, _delta, ok = loop_mod.run_replenish(
            manifest, operator_layer, loop_def, engine_override="mock"
        )

        assert enqueued == 0
        assert ok is True
        assert _pending_queue_files(operator_layer) == []

    def test_regressed_check_enqueues_one_fix_demand(self, operator_layer: Path) -> None:
        _seed_measurement(operator_layer, "bench", value=100.0, ts=1.0, passed=True)
        _seed_measurement(
            operator_layer, "bench", value=150.0, ts=2.0, run="run-2", passed=False
        )
        _write_regression_loop(operator_layer)
        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "heal")

        enqueued, delta, ok = loop_mod.run_replenish(
            manifest, operator_layer, loop_def, engine_override="mock", state=LoopState(name="heal")
        )

        assert enqueued == 1
        assert ok is True
        assert delta == {"engine_calls": 0.0, "usd": 0.0, "tokens": 0.0}
        [written] = _pending_queue_files(operator_layer)
        qt = QueueTask.model_validate(yaml.safe_load(written.read_text()))
        assert qt.flow == "ship"
        assert "Investigate and fix:" in qt.task
        assert "bench" in qt.task

    def test_fix_demand_carries_check_name_and_delta_as_feedback(
        self, operator_layer: Path
    ) -> None:
        _seed_measurement(operator_layer, "bench", value=100.0, ts=1.0, passed=True)
        _seed_measurement(
            operator_layer, "bench", value=150.0, ts=2.0, run="ci-run-42", passed=False
        )
        _write_regression_loop(operator_layer)
        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "heal")

        loop_mod.run_replenish(
            manifest, operator_layer, loop_def, engine_override="mock", state=LoopState(name="heal")
        )

        [written] = _pending_queue_files(operator_layer)
        qt = QueueTask.model_validate(yaml.safe_load(written.read_text()))
        # Reuses queue.build_retry_task's delimited failure-feedback pattern.
        assert "## Previous attempt failed" in qt.task
        assert "bench" in qt.task
        assert "100" in qt.task  # baseline
        assert "150" in qt.task  # regressed value
        assert "ci-run-42" in qt.task

    def test_recovered_check_is_not_flagged(self, operator_layer: Path) -> None:
        # A regression followed, in the SAME unseen window, by a recovery is
        # already resolved by the time this replenish looks — nothing to fix.
        _seed_measurement(operator_layer, "bench", value=100.0, ts=1.0, passed=True)
        _seed_measurement(
            operator_layer, "bench", value=150.0, ts=2.0, run="bad", passed=False
        )
        _seed_measurement(
            operator_layer, "bench", value=101.0, ts=3.0, run="fixed", passed=True
        )
        _write_regression_loop(operator_layer)
        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "heal")

        enqueued, _delta, ok = loop_mod.run_replenish(
            manifest, operator_layer, loop_def, engine_override="mock", state=LoopState(name="heal")
        )

        assert enqueued == 0
        assert ok is True

    def test_multiple_regressed_checks_enqueue_one_demand_each(
        self, operator_layer: Path
    ) -> None:
        _seed_measurement(operator_layer, "bench-a", value=10.0, ts=1.0, passed=True)
        _seed_measurement(
            operator_layer, "bench-a", value=20.0, ts=2.0, run="r", passed=False
        )
        _seed_measurement(operator_layer, "bench-b", value=5.0, ts=1.0, passed=True)
        _seed_measurement(
            operator_layer, "bench-b", value=9.0, ts=2.0, run="r", passed=False
        )
        _write_regression_loop(operator_layer)
        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "heal")

        enqueued, _delta, _ok = loop_mod.run_replenish(
            manifest, operator_layer, loop_def, engine_override="mock", state=LoopState(name="heal")
        )

        assert enqueued == 2
        tasks = [
            QueueTask.model_validate(yaml.safe_load(f.read_text()))
            for f in _pending_queue_files(operator_layer)
        ]
        checks_mentioned = {"bench-a" in t.task or "bench-b" in t.task for t in tasks}
        assert checks_mentioned == {True}

    def test_does_not_refire_the_same_regression_next_cycle(
        self, operator_layer: Path
    ) -> None:
        _seed_measurement(operator_layer, "bench", value=100.0, ts=1.0, passed=True)
        _seed_measurement(
            operator_layer, "bench", value=150.0, ts=2.0, run="r1", passed=False
        )
        _write_regression_loop(operator_layer)
        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "heal")
        state = LoopState(name="heal")

        first, _delta, _ok = loop_mod.run_replenish(
            manifest, operator_layer, loop_def, engine_override="mock", state=state
        )
        assert first == 1

        # Same state object, no new ledger data: nothing new happened.
        second, _delta, _ok = loop_mod.run_replenish(
            manifest, operator_layer, loop_def, engine_override="mock", state=state
        )
        assert second == 0

        # A genuinely NEW regression (fresh ledger record) fires again.
        _seed_measurement(
            operator_layer, "bench", value=200.0, ts=3.0, run="r2", passed=False
        )
        third, _delta, _ok = loop_mod.run_replenish(
            manifest, operator_layer, loop_def, engine_override="mock", state=state
        )
        assert third == 1

    def test_without_state_still_enqueues_but_cannot_persist(
        self, operator_layer: Path
    ) -> None:
        _seed_measurement(operator_layer, "bench", value=100.0, ts=1.0, passed=True)
        _seed_measurement(
            operator_layer, "bench", value=150.0, ts=2.0, run="r", passed=False
        )
        _write_regression_loop(operator_layer)
        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "heal")

        enqueued, _delta, ok = loop_mod.run_replenish(
            manifest, operator_layer, loop_def, engine_override="mock"
        )

        assert enqueued == 1
        assert ok is True

    def test_serial_drain_writes_non_isolated_demands(self, operator_layer: Path) -> None:
        _seed_measurement(operator_layer, "bench", value=100.0, ts=1.0, passed=True)
        _seed_measurement(
            operator_layer, "bench", value=150.0, ts=2.0, run="r", passed=False
        )
        _write_regression_loop(operator_layer)
        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "heal")
        assert loop_def.drain.concurrency == 1  # default

        loop_mod.run_replenish(manifest, operator_layer, loop_def, engine_override="mock")

        [written] = _pending_queue_files(operator_layer)
        qt = QueueTask.model_validate(yaml.safe_load(written.read_text()))
        assert qt.isolate is False

    def test_parallel_drain_writes_isolated_demands(self, operator_layer: Path) -> None:
        _seed_measurement(operator_layer, "bench", value=100.0, ts=1.0, passed=True)
        _seed_measurement(
            operator_layer, "bench", value=150.0, ts=2.0, run="r", passed=False
        )
        _write_regression_loop(operator_layer, concurrency=2)
        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "heal")

        loop_mod.run_replenish(manifest, operator_layer, loop_def, engine_override="mock")

        [written] = _pending_queue_files(operator_layer)
        qt = QueueTask.model_validate(yaml.safe_load(written.read_text()))
        assert qt.isolate is True

    def test_no_engine_call_no_budget_spent(self, operator_layer: Path) -> None:
        # The 'regression' kind never runs an engine turn — pure ledger read
        # plus a direct enqueue write.
        _seed_measurement(operator_layer, "bench", value=100.0, ts=1.0, passed=True)
        _seed_measurement(
            operator_layer, "bench", value=150.0, ts=2.0, run="r", passed=False
        )
        _write_regression_loop(operator_layer)
        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "heal")

        _enqueued, delta, _ok = loop_mod.run_replenish(
            manifest, operator_layer, loop_def, engine_override="mock"
        )

        assert delta == {"engine_calls": 0.0, "usd": 0.0, "tokens": 0.0}

    def test_dispatch_failure_sets_replenish_not_ok(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        import alc.conduct as conduct_mod

        _seed_measurement(operator_layer, "bench", value=100.0, ts=1.0, passed=True)
        _seed_measurement(
            operator_layer, "bench", value=150.0, ts=2.0, run="r", passed=False
        )
        _write_regression_loop(operator_layer)
        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "heal")

        def _boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(conduct_mod, "dispatch_enqueue", _boom)

        enqueued, _delta, ok = loop_mod.run_replenish(
            manifest, operator_layer, loop_def, engine_override="mock"
        )

        assert ok is False
        assert enqueued == 0


# ---------------------------------------------------------------------------
# End to end: a regression feeds a full cycle (replenish -> drain -> success)
# ---------------------------------------------------------------------------


class TestReplenishRegressionEndToEnd:
    def test_regression_becomes_a_successful_demand_in_one_cycle(
        self, operator_layer: Path
    ) -> None:
        _seed_measurement(operator_layer, "bench", value=100.0, ts=1.0, passed=True)
        _seed_measurement(
            operator_layer, "bench", value=150.0, ts=2.0, run="r", passed=False
        )
        _write_regression_loop(operator_layer)
        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "heal")

        new_state, record = run_cycle(
            manifest, operator_layer, loop_def, LoopState(name="heal"), engine_override="mock"
        )

        assert record.replenished == 1
        assert record.drained == 1
        assert record.succeeded == 1
        assert record.failed == 0
        # The cursor persisted into the returned state so a later cycle
        # (loaded from disk with this same state) won't re-fire.
        assert new_state.metric_cursor == {"bench": 2}
