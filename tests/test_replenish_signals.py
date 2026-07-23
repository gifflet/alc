# test_replenish_signals.py — Hermetic tests for roadmap-phase-5.md T3: the
# `signals` replenish kind (models.Replenish + loop.run_replenish) — the
# mechanism that turns pending signals into demands (via
# conduct.dispatch_enqueue, no planner turn) and archives each one consumed.
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
from alc.models import LoopDefinition, LoopState, QueueTask, Replenish, Signal
from alc.policy import validate_loop
from alc.signals import ingest, read_signals


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_loop(operator_layer: Path, name: str, body: str) -> None:
    loops = operator_layer / "loops"
    loops.mkdir(exist_ok=True)
    (loops / f"{name}.yaml").write_text(body)


def _write_signals_loop(
    operator_layer: Path, ref: str = "ship", task: str = "Investigate and fix:"
) -> None:
    _write_loop(
        operator_layer,
        "deliver",
        f"name: deliver\nreplenish:\n  kind: signals\n  ref: {ref}\n  task: \"{task}\"\n"
        "stop:\n  max_cycles: 20\n",
    )


def _seed_signal(
    operator_layer: Path,
    kind: str = "error",
    source: str = "sentry",
    title: str = "NullPointerException in checkout",
    body: str = "",
    ts: float = 100.0,
) -> Path:
    manifest = load_manifest(operator_layer)
    signals_dir = operator_layer.parent / manifest.signals_dir
    return ingest(
        signals_dir, Signal(kind=kind, source=source, title=title, body=body, ts=ts)
    )


def _pending_queue_files(operator_layer: Path) -> list[Path]:
    manifest = load_manifest(operator_layer)
    queue_dir = operator_layer.parent / manifest.queue_dir
    return sorted(queue_dir.glob("*.yaml")) if queue_dir.is_dir() else []


def _pending_signals(operator_layer: Path):
    manifest = load_manifest(operator_layer)
    return read_signals(operator_layer.parent / manifest.signals_dir)


# ---------------------------------------------------------------------------
# Replenish model — the 'signals' kind requires a ref (the target flow)
# ---------------------------------------------------------------------------


class TestReplenishSignalsModel:
    def test_signals_kind_requires_ref(self) -> None:
        with pytest.raises(ValidationError, match="ref"):
            Replenish(kind="signals", ref=None, task="Investigate:")

    def test_signals_kind_with_ref_is_valid(self) -> None:
        replenish = Replenish(kind="signals", ref="ship", task="Investigate:")
        assert replenish.kind == "signals"
        assert replenish.ref == "ship"


# ---------------------------------------------------------------------------
# Policy Gate — a signals-kind ref must name an existing flow
# ---------------------------------------------------------------------------


class TestReplenishSignalsValidation:
    def test_missing_flow_ref_yields_error_violation(self, operator_layer: Path) -> None:
        loop_def = LoopDefinition.model_validate(
            {
                "name": "bad-loop",
                "replenish": {"kind": "signals", "ref": "nonexistent", "task": "fix:"},
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
                "replenish": {"kind": "signals", "ref": "ship", "task": "fix:"},
                "stop": {"max_cycles": 5},
            }
        )
        manifest = load_manifest(operator_layer)
        violations = validate_loop(manifest, operator_layer, loop_def)
        error_rules = [v.rule for v in violations if v.severity == "error"]
        assert "loop-replenish-flow-exists" not in error_rules


# ---------------------------------------------------------------------------
# run_replenish — dispatch
# ---------------------------------------------------------------------------


class TestReplenishSignalsDispatch:
    def test_prints_header(self, operator_layer: Path, capsys) -> None:
        _write_signals_loop(operator_layer)
        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")

        loop_mod.run_replenish(manifest, operator_layer, loop_def, engine_override="mock")

        err = capsys.readouterr().err
        assert "▶ replenish — signals:ship" in err

    def test_no_pending_signals_is_a_no_op(self, operator_layer: Path) -> None:
        _write_signals_loop(operator_layer)
        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")

        enqueued, delta, ok = loop_mod.run_replenish(
            manifest, operator_layer, loop_def, engine_override="mock"
        )

        assert enqueued == 0
        assert delta == {"engine_calls": 0.0, "usd": 0.0, "tokens": 0.0}
        assert ok is True
        assert _pending_queue_files(operator_layer) == []

    def test_one_signal_enqueues_one_demand_and_archives_it(
        self, operator_layer: Path
    ) -> None:
        _seed_signal(operator_layer, title="Checkout crashes on Safari")
        _write_signals_loop(operator_layer)
        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")

        enqueued, _delta, _ok = loop_mod.run_replenish(
            manifest, operator_layer, loop_def, engine_override="mock"
        )

        assert enqueued == 1
        [written] = _pending_queue_files(operator_layer)
        qt = QueueTask.model_validate(yaml.safe_load(written.read_text()))
        assert qt.flow == "ship"
        assert "Checkout crashes on Safari" in qt.task
        assert "Investigate and fix:" in qt.task

        # The consumed signal is archived, not left pending.
        assert _pending_signals(operator_layer) == []

    def test_task_text_carries_kind_source_and_body(
        self, operator_layer: Path
    ) -> None:
        _seed_signal(
            operator_layer,
            kind="issue",
            source="linear",
            title="Onboarding is confusing",
            body="Three users reported this today.",
        )
        _write_signals_loop(operator_layer)
        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")

        loop_mod.run_replenish(manifest, operator_layer, loop_def, engine_override="mock")

        [written] = _pending_queue_files(operator_layer)
        qt = QueueTask.model_validate(yaml.safe_load(written.read_text()))
        assert "issue" in qt.task
        assert "linear" in qt.task
        assert "Three users reported this today." in qt.task

    def test_multiple_signals_enqueue_one_demand_each(
        self, operator_layer: Path
    ) -> None:
        _seed_signal(operator_layer, title="first", ts=100.0)
        _seed_signal(operator_layer, title="second", ts=200.0)
        _write_signals_loop(operator_layer)
        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")

        enqueued, _delta, _ok = loop_mod.run_replenish(
            manifest, operator_layer, loop_def, engine_override="mock"
        )

        assert enqueued == 2
        assert len(_pending_queue_files(operator_layer)) == 2
        assert _pending_signals(operator_layer) == []

    def test_malformed_signal_file_is_skipped_not_fatal(
        self, operator_layer: Path
    ) -> None:
        _seed_signal(operator_layer, title="good one")
        manifest = load_manifest(operator_layer)
        signals_dir = operator_layer.parent / manifest.signals_dir
        (signals_dir / "corrupt.json").write_text("not json at all")
        _write_signals_loop(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")

        enqueued, _delta, ok = loop_mod.run_replenish(
            manifest, operator_layer, loop_def, engine_override="mock"
        )

        assert enqueued == 1
        assert ok is True
        [written] = _pending_queue_files(operator_layer)
        qt = QueueTask.model_validate(yaml.safe_load(written.read_text()))
        assert "good one" in qt.task
        # The corrupt file was never touched (not archived, not crashed on).
        assert (signals_dir / "corrupt.json").exists()

    def test_serial_drain_writes_non_isolated_demands(
        self, operator_layer: Path
    ) -> None:
        _seed_signal(operator_layer)
        _write_signals_loop(operator_layer)
        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        assert loop_def.drain.concurrency == 1  # default

        loop_mod.run_replenish(manifest, operator_layer, loop_def, engine_override="mock")

        [written] = _pending_queue_files(operator_layer)
        qt = QueueTask.model_validate(yaml.safe_load(written.read_text()))
        assert qt.isolate is False

    def test_parallel_drain_writes_isolated_demands(
        self, operator_layer: Path
    ) -> None:
        _seed_signal(operator_layer)
        _write_loop(
            operator_layer,
            "deliver",
            "name: deliver\nreplenish:\n  kind: signals\n  ref: ship\n  task: \"fix:\"\n"
            "stop:\n  max_cycles: 20\ndrain:\n  concurrency: 2\n",
        )
        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")

        loop_mod.run_replenish(manifest, operator_layer, loop_def, engine_override="mock")

        [written] = _pending_queue_files(operator_layer)
        qt = QueueTask.model_validate(yaml.safe_load(written.read_text()))
        assert qt.isolate is True

    def test_no_engine_call_no_budget_spent(self, operator_layer: Path) -> None:
        # The 'signals' kind never runs an engine turn (no planner) — same
        # direct-write contract as `alc enqueue`.
        _seed_signal(operator_layer)
        _write_signals_loop(operator_layer)
        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")

        _enqueued, delta, _ok = loop_mod.run_replenish(
            manifest, operator_layer, loop_def, engine_override="mock"
        )

        assert delta == {"engine_calls": 0.0, "usd": 0.0, "tokens": 0.0}

    def test_enqueue_happens_before_archive(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        """Crash-safety: if the process dies between the two steps, the worst
        case is a re-processed signal (a duplicate demand), never a lost one.
        This only holds if enqueue always runs BEFORE archive."""
        import alc.conduct as conduct_mod
        import alc.signals as signals_mod

        _seed_signal(operator_layer)
        _write_signals_loop(operator_layer)
        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")

        call_order: list[str] = []
        real_dispatch = conduct_mod.dispatch_enqueue
        real_archive = signals_mod.archive_signal

        def _spy_dispatch(*args, **kwargs):
            call_order.append("enqueue")
            return real_dispatch(*args, **kwargs)

        def _spy_archive(*args, **kwargs):
            call_order.append("archive")
            return real_archive(*args, **kwargs)

        monkeypatch.setattr(conduct_mod, "dispatch_enqueue", _spy_dispatch)
        monkeypatch.setattr(signals_mod, "archive_signal", _spy_archive)

        loop_mod.run_replenish(manifest, operator_layer, loop_def, engine_override="mock")

        assert call_order == ["enqueue", "archive"]


# ---------------------------------------------------------------------------
# End to end: a signal feeds a full cycle (replenish -> drain -> success)
# ---------------------------------------------------------------------------


class TestReplenishSignalsEndToEnd:
    def test_signal_becomes_a_successful_demand_in_one_cycle(
        self, operator_layer: Path
    ) -> None:
        _seed_signal(operator_layer, title="Checkout crashes on Safari")
        _write_signals_loop(operator_layer)
        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")

        _new_state, record = run_cycle(
            manifest, operator_layer, loop_def, LoopState(name="deliver"), engine_override="mock"
        )

        assert record.replenished == 1
        assert record.drained == 1
        assert record.succeeded == 1
        assert record.failed == 0
        assert _pending_signals(operator_layer) == []
