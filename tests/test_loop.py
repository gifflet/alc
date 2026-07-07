# test_loop.py — Hermetic tests for the Autonomous Loop: models, usage plumbing,
# run_cycle, stop conditions, replenish counting, and the cycle/loop CLI.
#
# Fully hermetic: MockEngine, tmp_path, and isolate:false queue tasks so no real
# model and no git repository are ever needed.
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
import yaml

from alc.assurance import AssuranceLoop
from alc.engine import Capabilities, EngineRequest, EngineResult, Usage
from alc.engines.mock import MockEngine
from alc.intake import load_loop, load_manifest
from alc.loop import (
    check_post_stop,
    check_pre_stop,
    ledger_path,
    load_loop_state,
    loops_dir,
    read_ledger,
    run_cycle,
    state_path,
)
from alc.models import (
    Check,
    CycleRecord,
    LoopDefinition,
    LoopState,
)
from alc.verifier import Verifier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_LOOP_MODE_B = """\
name: deliver
stop:
  max_cycles: 20
"""

_MARKER_TASK = """\
flow: ship
task: "tidy"
engine: mock
isolate: false
"""


class _UsageEngine:
    """A mock engine that reports a fixed Usage on every turn (for budget tests)."""

    name = "mock"

    def __init__(self, cost: float = 0.5, in_tok: int = 10, out_tok: int = 20) -> None:
        self._cost = cost
        self._in = in_tok
        self._out = out_tok

    def capabilities(self) -> Capabilities:
        return Capabilities()

    def health_check(self) -> bool:
        return True

    def run(self, request: EngineRequest) -> EngineResult:
        return EngineResult(
            ok=True,
            output_text="[mock] applied",
            usage=Usage(input_tokens=self._in, output_tokens=self._out, cost_usd=self._cost),
        )


def _write_loop(operator_layer: Path, name: str, body: str) -> None:
    """Write a loop definition YAML into the loops dir."""
    loops = operator_layer / "loops"
    loops.mkdir(exist_ok=True)
    (loops / f"{name}.yaml").write_text(body)


def _seed_queue(operator_layer: Path, stem: str, body: str = _MARKER_TASK) -> None:
    """Drop one pending task file into the queue dir."""
    queue_dir = operator_layer / "queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    (queue_dir / f"{stem}.yaml").write_text(body)


def _failing_blueprint(operator_layer: Path) -> None:
    """Write a blueprint whose only check always fails, and a flow that uses it."""
    (operator_layer / "blueprints" / "failing.md").write_text(
        "---\nname: failing\npurpose: Always fails its check.\ncompute_tier: standard\n"
        'checks:\n  - name: nope\n    command: ["false"]\n---\n# Workflow\n1. Nothing.\n'
    )
    (operator_layer / "flows" / "bad.yaml").write_text(
        "name: bad\ndescription: fails.\nstages:\n  - name: b\n    blueprint: failing\n"
    )


_FAILING_TASK = """\
flow: bad
task: "fail me"
engine: mock
isolate: false
"""


# ---------------------------------------------------------------------------
# Models: round-trip + validators
# ---------------------------------------------------------------------------


class TestLoopModels:
    def test_definition_round_trip_from_yaml(self) -> None:
        raw = (
            "name: deliver\n"
            "replenish:\n  kind: specialist\n  ref: pm\n  task: plan the next version\n"
            "stop:\n  max_cycles: 20\n  on_no_new_work: true\n"
            "  budget:\n    unit: engine_calls\n    max: 100\n"
            "failure:\n  max_consecutive: 3\n"
            "drain:\n  concurrency: 2\n"
        )
        loop_def = LoopDefinition.model_validate(yaml.safe_load(raw))
        assert loop_def.name == "deliver"
        assert loop_def.replenish.kind == "specialist"
        assert loop_def.replenish.ref == "pm"
        assert loop_def.stop.max_cycles == 20
        assert loop_def.stop.budget.unit == "engine_calls"
        assert loop_def.stop.budget.max == 100
        assert loop_def.failure.max_consecutive == 3
        assert loop_def.drain.concurrency == 2

    def test_mode_b_defaults(self) -> None:
        loop_def = LoopDefinition.model_validate(yaml.safe_load(_LOOP_MODE_B))
        assert loop_def.replenish is None
        assert loop_def.stop.on_no_new_work is True
        assert loop_def.failure.max_consecutive == 5
        assert loop_def.drain.concurrency == 1

    def test_rejects_non_positive_max_cycles(self) -> None:
        with pytest.raises(ValueError, match="max_cycles"):
            LoopDefinition.model_validate({"name": "x", "stop": {"max_cycles": 0}})

    def test_rejects_non_positive_budget_max(self) -> None:
        with pytest.raises(ValueError, match="max"):
            LoopDefinition.model_validate(
                {"name": "x", "stop": {"max_cycles": 5, "budget": {"unit": "usd", "max": 0}}}
            )

    def test_rejects_max_consecutive_below_one(self) -> None:
        with pytest.raises(ValueError, match="max_consecutive"):
            LoopDefinition.model_validate(
                {"name": "x", "stop": {"max_cycles": 5}, "failure": {"max_consecutive": 0}}
            )

    def test_rejects_bad_budget_unit(self) -> None:
        with pytest.raises(ValueError):
            LoopDefinition.model_validate(
                {"name": "x", "stop": {"max_cycles": 5, "budget": {"unit": "widgets", "max": 3}}}
            )


# ---------------------------------------------------------------------------
# Usage plumbing: RunReport.usage populated + aggregated across attempts
# ---------------------------------------------------------------------------


def _marker_checks() -> list[Check]:
    return [Check(name="marker", command=["test", "-f", "done.txt"])]


class TestUsagePlumbing:
    def test_single_attempt_usage_populated(self, tmp_path: Path) -> None:
        (tmp_path / "done.txt").write_text("ok")
        loop = AssuranceLoop(engine=_UsageEngine(cost=0.5), verifier=Verifier(), max_repairs=3)
        report = loop.run(
            EngineRequest(directive="do it", workdir=tmp_path), checks=_marker_checks()
        )
        assert report.success is True
        assert report.usage is not None
        assert report.usage.cost_usd == 0.5
        assert report.usage.input_tokens == 10
        assert report.usage.output_tokens == 20

    def test_usage_aggregated_across_attempts(self, tmp_path: Path) -> None:
        # Attempt 0 fails the check, attempt 1 creates the file — two engine turns.
        class _RepairUsageEngine(_UsageEngine):
            def __init__(self) -> None:
                super().__init__(cost=1.0, in_tok=5, out_tok=7)
                self._n = 0

            def run(self, request: EngineRequest) -> EngineResult:
                self._n += 1
                if self._n == 2:
                    (request.workdir / "done.txt").write_text("ok")
                return super().run(request)

        loop = AssuranceLoop(engine=_RepairUsageEngine(), verifier=Verifier(), max_repairs=3)
        report = loop.run(
            EngineRequest(directive="do it", workdir=tmp_path), checks=_marker_checks()
        )
        assert report.success is True
        assert len(report.attempts) == 2
        # Two turns -> summed usage.
        assert report.usage.cost_usd == 2.0
        assert report.usage.input_tokens == 10
        assert report.usage.output_tokens == 14

    def test_usage_none_when_engine_reports_nothing(self, tmp_path: Path) -> None:
        (tmp_path / "done.txt").write_text("ok")
        loop = AssuranceLoop(engine=MockEngine(), verifier=Verifier(), max_repairs=3)
        report = loop.run(
            EngineRequest(directive="do it", workdir=tmp_path), checks=_marker_checks()
        )
        assert report.usage is None


# ---------------------------------------------------------------------------
# run_cycle — Mode B (drain-only)
# ---------------------------------------------------------------------------


class TestRunCycleModeB:
    def test_drains_and_advances_state(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        _write_loop(operator_layer, "deliver", _LOOP_MODE_B)
        _seed_queue(operator_layer, "t1")

        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        state = LoopState(name="deliver")

        new_state, record = run_cycle(
            manifest, operator_layer, loop_def, state, engine_override="mock"
        )

        assert new_state.cycle == 1
        assert record.replenished == 0        # Mode B
        assert record.drained == 1
        assert record.succeeded == 1
        assert record.failed == 0
        assert record.progress is True
        assert new_state.status == "running"

        # A ledger line was appended.
        records = read_ledger(ledger_path(loops_dir(manifest, operator_layer), "deliver"))
        assert len(records) == 1
        assert records[0].cycle == 1

    def test_engine_calls_counted_in_budget_delta(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        _write_loop(operator_layer, "deliver", _LOOP_MODE_B)
        _seed_queue(operator_layer, "t1")

        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        _new_state, record = run_cycle(
            manifest, operator_layer, loop_def, LoopState(name="deliver"), engine_override="mock"
        )
        # ship flow = plan + build stages -> 2 engine attempts minimum.
        assert record.budget_delta["engine_calls"] >= 2


# ---------------------------------------------------------------------------
# Stop: max_cycles pre-check no-op
# ---------------------------------------------------------------------------


class TestStopMaxCycles:
    def test_pre_stop_no_ops_when_cycles_reached(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        _write_loop(operator_layer, "deliver", "name: deliver\nstop:\n  max_cycles: 2\n")
        _seed_queue(operator_layer, "t1")

        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        # State already at the cap.
        state = LoopState(name="deliver", cycle=2)

        new_state, record = run_cycle(
            manifest, operator_layer, loop_def, state, engine_override="mock"
        )
        assert new_state.status == "stopped"
        assert new_state.stopped_reason == "max_cycles"
        assert record.drained == 0            # queue not drained by a pre-stop
        # The seeded task remains untouched.
        assert (operator_layer / "queue" / "t1.yaml").exists()


# ---------------------------------------------------------------------------
# Stop: on_no_new_work
# ---------------------------------------------------------------------------


class TestStopNoNewWork:
    def test_stops_when_nothing_replenished_or_drained(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        _write_loop(operator_layer, "deliver", _LOOP_MODE_B)  # Mode B, empty queue

        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        new_state, record = run_cycle(
            manifest, operator_layer, loop_def, LoopState(name="deliver"), engine_override="mock"
        )
        assert record.replenished == 0
        assert record.drained == 0
        assert new_state.status == "stopped"
        assert new_state.stopped_reason == "no_new_work"


# ---------------------------------------------------------------------------
# Stop: failures (consecutive no-progress) + reset on progress
# ---------------------------------------------------------------------------


class TestStopFailures:
    def test_stops_after_consecutive_no_progress(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        _failing_blueprint(operator_layer)
        _write_loop(
            operator_layer,
            "deliver",
            "name: deliver\nstop:\n  max_cycles: 20\n  on_no_new_work: false\n"
            "failure:\n  max_consecutive: 2\n",
        )
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        state = LoopState(name="deliver")

        # Cycle 1: seed a failing task -> no progress (counter = 1).
        _seed_queue(operator_layer, "f1", _FAILING_TASK)
        state, rec1 = run_cycle(manifest, operator_layer, loop_def, state, engine_override="mock")
        assert rec1.progress is False
        assert state.consecutive_no_progress == 1
        assert state.status == "running"

        # Cycle 2: re-seed a failing task -> counter hits 2 -> stop "failures".
        _seed_queue(operator_layer, "f2", _FAILING_TASK)
        state, rec2 = run_cycle(manifest, operator_layer, loop_def, state, engine_override="mock")
        assert state.consecutive_no_progress == 2
        assert state.status == "stopped"
        assert state.stopped_reason == "failures"

    def test_progress_cycle_resets_counter(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        _failing_blueprint(operator_layer)
        _write_loop(
            operator_layer,
            "deliver",
            "name: deliver\nstop:\n  max_cycles: 20\n  on_no_new_work: false\n"
            "failure:\n  max_consecutive: 3\n",
        )
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        state = LoopState(name="deliver", consecutive_no_progress=2)

        # A passing task -> progress -> counter resets to 0.
        _seed_queue(operator_layer, "ok1", _MARKER_TASK)
        state, rec = run_cycle(manifest, operator_layer, loop_def, state, engine_override="mock")
        assert rec.progress is True
        assert state.consecutive_no_progress == 0
        assert state.status == "running"


# ---------------------------------------------------------------------------
# Stop: budget (engine_calls cap and usd cap)
# ---------------------------------------------------------------------------


class TestStopBudget:
    def test_engine_calls_cap_triggers(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        _write_loop(
            operator_layer,
            "deliver",
            "name: deliver\nstop:\n  max_cycles: 20\n  on_no_new_work: false\n"
            "  budget:\n    unit: engine_calls\n    max: 1\n",
        )
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        _seed_queue(operator_layer, "t1")

        new_state, record = run_cycle(
            manifest, operator_layer, loop_def, LoopState(name="deliver"), engine_override="mock"
        )
        # ship flow >= 2 engine calls > cap of 1 -> budget stop.
        assert new_state.budget_used["engine_calls"] >= 2
        assert new_state.status == "stopped"
        assert new_state.stopped_reason == "budget"

    def test_usd_cap_triggers_with_reporting_engine(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        manifest = load_manifest(operator_layer)
        _write_loop(
            operator_layer,
            "deliver",
            "name: deliver\nstop:\n  max_cycles: 20\n  on_no_new_work: false\n"
            "  budget:\n    unit: usd\n    max: 0.4\n",
        )
        # Make every engine turn report a cost so the usd budget accumulates.
        # execute_mandate resolves the engine via runner's own import of
        # resolve_engine, so patch that binding (as the conduct tests do).
        monkeypatch.setattr(
            "alc.runner.resolve_engine",
            lambda name, engines: _UsageEngine(cost=0.5),
        )
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        _seed_queue(operator_layer, "t1")

        new_state, record = run_cycle(
            manifest, operator_layer, loop_def, LoopState(name="deliver"), engine_override="mock"
        )
        assert new_state.budget_used["usd"] >= 0.5
        assert new_state.status == "stopped"
        assert new_state.stopped_reason == "budget"

    def test_check_pre_and_post_stop_direct(self) -> None:
        loop_def = LoopDefinition.model_validate(
            {
                "name": "d",
                "stop": {"max_cycles": 5, "budget": {"unit": "usd", "max": 10}},
                "failure": {"max_consecutive": 3},
            }
        )
        # Pre-stop: budget already exceeded.
        over = LoopState(name="d", cycle=1, budget_used={"usd": 12.0})
        assert check_pre_stop(loop_def, over) == "budget"
        # Pre-stop: cycles reached.
        capped = LoopState(name="d", cycle=5)
        assert check_pre_stop(loop_def, capped) == "max_cycles"
        # Pre-stop: nothing holds.
        fresh = LoopState(name="d", cycle=0, budget_used={"usd": 1.0})
        assert check_pre_stop(loop_def, fresh) is None
        # Post-stop: failures win over budget/max_cycles when the counter is high.
        state = LoopState(name="d", cycle=1, consecutive_no_progress=3)
        rec = CycleRecord(
            cycle=1, replenished=1, drained=1, succeeded=0, failed=1,
            progress=False, budget_delta={},
        )
        assert check_post_stop(loop_def, state, rec) == "failures"


# ---------------------------------------------------------------------------
# Budget-unit-unmeasurable WARN
# ---------------------------------------------------------------------------


class TestBudgetUnitWarn:
    """Covers the PRD requirement: warn when a usd/tokens cap is inert for a cycle."""

    def test_warns_when_usd_unit_reports_nothing(
        self, operator_layer: Path, capsys
    ) -> None:
        """Engine runs (engine_calls > 0) but reports no usd cost -> WARN emitted."""
        manifest = load_manifest(operator_layer)
        _write_loop(
            operator_layer,
            "deliver",
            "name: deliver\nstop:\n  max_cycles: 20\n  on_no_new_work: false\n"
            "  budget:\n    unit: usd\n    max: 100\n",
        )
        # MockEngine reports no Usage (cost_usd stays None / 0), but the ship flow
        # DOES run engine turns, so engine_calls > 0 after the cycle.
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        _seed_queue(operator_layer, "t1")

        run_cycle(
            manifest, operator_layer, loop_def, LoopState(name="deliver"), engine_override="mock"
        )

        err = capsys.readouterr().err
        assert "[WARN] budget unit 'usd'" in err
        assert "max_cycles remains the backstop" in err

    def test_no_warn_when_usd_cost_is_reported(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        """Engine reports a real usd cost -> no WARN."""
        manifest = load_manifest(operator_layer)
        _write_loop(
            operator_layer,
            "deliver",
            "name: deliver\nstop:\n  max_cycles: 20\n  on_no_new_work: false\n"
            "  budget:\n    unit: usd\n    max: 100\n",
        )
        monkeypatch.setattr(
            "alc.runner.resolve_engine",
            lambda name, engines: _UsageEngine(cost=0.5),
        )
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        _seed_queue(operator_layer, "t1")

        run_cycle(
            manifest, operator_layer, loop_def, LoopState(name="deliver"), engine_override="mock"
        )

        err = capsys.readouterr().err
        assert "[WARN] budget unit 'usd'" not in err

    def test_no_warn_on_empty_cycle_with_usd_budget(
        self, operator_layer: Path, capsys
    ) -> None:
        """Mode B empty cycle (engine_calls == 0, queue empty) -> no WARN."""
        manifest = load_manifest(operator_layer)
        _write_loop(
            operator_layer,
            "deliver",
            # on_no_new_work: false so the empty cycle is not a pre-stop;
            # the cycle runs but drains nothing (engine_calls stays 0).
            "name: deliver\nstop:\n  max_cycles: 20\n  on_no_new_work: false\n"
            "  budget:\n    unit: usd\n    max: 100\n",
        )
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        # No task seeded -> queue is empty -> engine_calls == 0 after the cycle.

        run_cycle(
            manifest, operator_layer, loop_def, LoopState(name="deliver"), engine_override="mock"
        )

        err = capsys.readouterr().err
        assert "[WARN] budget unit 'usd'" not in err


# ---------------------------------------------------------------------------
# Replenish counting
# ---------------------------------------------------------------------------


class TestReplenishCounting:
    def test_specialist_replenish_counts_enqueued(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        from alc import loop as loop_mod

        # Write a specialist definition referenced by the loop.
        specialists_dir = operator_layer / "specialists"
        specialists_dir.mkdir(exist_ok=True)
        (specialists_dir / "pm.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": "pm",
                    "area": "planning",
                    "blueprint": "chore",
                    "knowledge_path": ".alc/specialists/pm.knowledge.md",
                }
            )
        )
        _write_loop(
            operator_layer,
            "deliver",
            "name: deliver\nreplenish:\n  kind: specialist\n  ref: pm\n  task: plan\n"
            "stop:\n  max_cycles: 20\n",
        )

        # Fake run_specialist: instead of running a real Specialist, it self-enqueues
        # two queue tasks (simulating a planner that emits demands).
        def _fake_run_specialist(*, manifest, operator_layer, specialist, task, engine_override):
            from alc.models import RunReport, Scorecard, SpecialistReport

            queue_dir = operator_layer.parent / manifest.queue_dir
            queue_dir.mkdir(parents=True, exist_ok=True)
            for i in range(2):
                (queue_dir / f"planned-{i}.yaml").write_text(_MARKER_TASK)
            act = RunReport(
                blueprint="chore", engine="mock", success=True, attempts=[],
                scorecard=Scorecard(span=0, passes=0, streak=0, touch=0), output_text="",
            )
            return SpecialistReport(specialist=specialist.name, act=act, knowledge_updated=False)

        monkeypatch.setattr("alc.specialist.run_specialist", _fake_run_specialist)

        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        enqueued, delta = loop_mod.run_replenish(
            manifest, operator_layer, loop_def, engine_override="mock"
        )
        assert enqueued == 2

    def test_run_cycle_reports_replenished(self, operator_layer: Path, monkeypatch) -> None:
        specialists_dir = operator_layer / "specialists"
        specialists_dir.mkdir(exist_ok=True)
        (specialists_dir / "pm.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": "pm",
                    "area": "planning",
                    "blueprint": "chore",
                    "knowledge_path": ".alc/specialists/pm.knowledge.md",
                }
            )
        )
        _write_loop(
            operator_layer,
            "deliver",
            "name: deliver\nreplenish:\n  kind: specialist\n  ref: pm\n  task: plan\n"
            "stop:\n  max_cycles: 20\n",
        )

        def _fake_run_specialist(*, manifest, operator_layer, specialist, task, engine_override):
            from alc.models import RunReport, Scorecard, SpecialistReport

            queue_dir = operator_layer.parent / manifest.queue_dir
            queue_dir.mkdir(parents=True, exist_ok=True)
            (queue_dir / "planned-0.yaml").write_text(_MARKER_TASK)
            act = RunReport(
                blueprint="chore", engine="mock", success=True, attempts=[],
                scorecard=Scorecard(span=0, passes=0, streak=0, touch=0), output_text="",
            )
            return SpecialistReport(specialist=specialist.name, act=act, knowledge_updated=False)

        monkeypatch.setattr("alc.specialist.run_specialist", _fake_run_specialist)

        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        _new_state, record = run_cycle(
            manifest, operator_layer, loop_def, LoopState(name="deliver"), engine_override="mock"
        )
        # One task planned, then drained in the same cycle.
        assert record.replenished == 1
        assert record.drained == 1
        assert record.succeeded == 1


# ---------------------------------------------------------------------------
# CLI: cmd_cycle / cmd_loop
# ---------------------------------------------------------------------------


def _chdir_to_project(operator_layer: Path, monkeypatch) -> None:
    """chdir into the project root so _find_operator_layer resolves this .alc/."""
    monkeypatch.chdir(operator_layer.parent)


class TestCliCycle:
    def test_status_prints_state(self, operator_layer: Path, monkeypatch, capsys) -> None:
        from alc.cli import cmd_cycle

        _write_loop(operator_layer, "deliver", _LOOP_MODE_B)
        _chdir_to_project(operator_layer, monkeypatch)

        args = argparse.Namespace(
            name="deliver", engine=None, concurrency=0, status=True, reset=False
        )
        assert cmd_cycle(args) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["name"] == "deliver"
        # A never-run loop reports "pending", not "running".
        assert out["status"] == "pending"
        assert out["cycle"] == 0

    def test_reset_writes_fresh_state(self, operator_layer: Path, monkeypatch, capsys) -> None:
        from alc.cli import cmd_cycle

        _write_loop(operator_layer, "deliver", _LOOP_MODE_B)
        _chdir_to_project(operator_layer, monkeypatch)

        # Pre-write a stopped state.
        spath = state_path(loops_dir(load_manifest(operator_layer), operator_layer), "deliver")
        spath.parent.mkdir(parents=True, exist_ok=True)
        spath.write_text(
            LoopState(name="deliver", status="stopped", cycle=9, stopped_reason="max_cycles")
            .model_dump_json()
        )

        args = argparse.Namespace(
            name="deliver", engine=None, concurrency=0, status=False, reset=True
        )
        assert cmd_cycle(args) == 0
        assert "reset" in capsys.readouterr().out.lower()
        reloaded = load_loop_state(spath, "deliver")
        # --reset must return the state to "pending" (never-run).
        assert reloaded.status == "pending"
        assert reloaded.cycle == 0

    def test_stopped_loop_is_no_op(self, operator_layer: Path, monkeypatch, capsys) -> None:
        from alc.cli import cmd_cycle

        _write_loop(operator_layer, "deliver", _LOOP_MODE_B)
        _chdir_to_project(operator_layer, monkeypatch)
        spath = state_path(loops_dir(load_manifest(operator_layer), operator_layer), "deliver")
        spath.parent.mkdir(parents=True, exist_ok=True)
        spath.write_text(
            LoopState(name="deliver", status="stopped", stopped_reason="no_new_work")
            .model_dump_json()
        )

        args = argparse.Namespace(
            name="deliver", engine=None, concurrency=0, status=False, reset=False
        )
        assert cmd_cycle(args) == 0
        out = capsys.readouterr().out
        assert "already stopped" in out
        assert "no_new_work" in out

    def test_missing_loop_errors(self, operator_layer: Path, monkeypatch) -> None:
        from alc.cli import cmd_cycle

        _chdir_to_project(operator_layer, monkeypatch)
        args = argparse.Namespace(
            name="nope", engine=None, concurrency=0, status=False, reset=False
        )
        assert cmd_cycle(args) == 1

    def test_runs_one_cycle_end_to_end(self, operator_layer: Path, monkeypatch, capsys) -> None:
        from alc.cli import cmd_cycle

        _write_loop(operator_layer, "deliver", _LOOP_MODE_B)
        _seed_queue(operator_layer, "t1")
        _chdir_to_project(operator_layer, monkeypatch)

        args = argparse.Namespace(
            name="deliver", engine="mock", concurrency=0, status=False, reset=False
        )
        assert cmd_cycle(args) == 0
        assert "cycle 1:" in capsys.readouterr().out

        spath = state_path(loops_dir(load_manifest(operator_layer), operator_layer), "deliver")
        state = load_loop_state(spath, "deliver")
        assert state.cycle == 1

    def test_pending_loop_runs_cycle_not_no_op(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        """A pending loop must NOT hit the already-stopped no-op path."""
        from alc.cli import cmd_cycle

        _write_loop(operator_layer, "deliver", _LOOP_MODE_B)
        _seed_queue(operator_layer, "t1")
        _chdir_to_project(operator_layer, monkeypatch)

        # Write an explicit pending state to confirm that pending != stopped.
        spath = state_path(loops_dir(load_manifest(operator_layer), operator_layer), "deliver")
        spath.parent.mkdir(parents=True, exist_ok=True)
        spath.write_text(LoopState(name="deliver", status="pending").model_dump_json())

        args = argparse.Namespace(
            name="deliver", engine="mock", concurrency=0, status=False, reset=False
        )
        assert cmd_cycle(args) == 0
        out = capsys.readouterr().out
        # A cycle ran — the no-op "already stopped" message must NOT appear.
        assert "already stopped" not in out
        assert "cycle 1:" in out


# ---------------------------------------------------------------------------
# Three-state machine: pending -> running -> stopped
# ---------------------------------------------------------------------------


class TestPendingState:
    def test_fresh_state_no_file_is_pending(self, tmp_path: Path) -> None:
        """load_loop_state returns status=pending when no file exists."""
        missing = tmp_path / "nonexistent.state.json"
        state = load_loop_state(missing, "myloop")
        assert state.status == "pending"
        assert state.cycle == 0

    def test_after_one_non_stopping_cycle_status_is_running(
        self, operator_layer: Path
    ) -> None:
        """First completed cycle transitions pending -> running."""
        manifest = load_manifest(operator_layer)
        _write_loop(operator_layer, "deliver", _LOOP_MODE_B)
        _seed_queue(operator_layer, "t1")

        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        state = LoopState(name="deliver")  # default: pending
        assert state.status == "pending"

        new_state, record = run_cycle(
            manifest, operator_layer, loop_def, state, engine_override="mock"
        )
        assert new_state.status == "running"
        assert new_state.cycle == 1
        assert record.stopped_reason is None

    def test_stop_condition_yields_stopped(self, operator_layer: Path) -> None:
        """When a stop fires the status transitions directly to stopped."""
        manifest = load_manifest(operator_layer)
        # max_cycles=1 so after one cycle the post-check fires max_cycles.
        _write_loop(
            operator_layer,
            "deliver",
            "name: deliver\nstop:\n  max_cycles: 1\n  on_no_new_work: false\n",
        )
        _seed_queue(operator_layer, "t1")

        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        state = LoopState(name="deliver")

        new_state, record = run_cycle(
            manifest, operator_layer, loop_def, state, engine_override="mock"
        )
        assert new_state.status == "stopped"
        assert new_state.stopped_reason == "max_cycles"

    def test_reset_returns_state_to_pending(self, tmp_path: Path) -> None:
        """LoopState constructed fresh (as --reset does) has status=pending."""
        state = LoopState(name="myloop", status="stopped", cycle=5, stopped_reason="budget")
        reset_state = LoopState(name=state.name)
        assert reset_state.status == "pending"
        assert reset_state.cycle == 0
        assert reset_state.stopped_reason is None


class TestCliLoop:
    def test_loop_terminates_at_max_cycles(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        from alc.cli import cmd_loop

        # Mode B with a self-refilling queue would run forever; instead use a
        # max_cycles=2 loop and re-seed the queue between cycles so each cycle
        # drains one task (progress) and the loop stops at the cycle cap.
        _write_loop(
            operator_layer,
            "deliver",
            "name: deliver\nstop:\n  max_cycles: 2\n  on_no_new_work: false\n",
        )
        _chdir_to_project(operator_layer, monkeypatch)

        # Re-seed the queue before every run_cycle so it never trips no_new_work
        # and always makes progress; the max_cycles cap is what terminates it.
        # cmd_loop imports run_cycle from alc.loop inside the function body, so
        # patching alc.loop.run_cycle rebinds the name for every call.
        import alc.loop as loop_mod

        real_run_cycle = loop_mod.run_cycle
        seed = {"n": 0}

        def _seeding_run_cycle(manifest, operator_layer, loop_def, state, engine_override=None):
            _seed_queue(operator_layer, f"auto-{seed['n']}")
            seed["n"] += 1
            return real_run_cycle(
                manifest, operator_layer, loop_def, state, engine_override=engine_override
            )

        monkeypatch.setattr(loop_mod, "run_cycle", _seeding_run_cycle)

        args = argparse.Namespace(name="deliver", engine="mock", interval=0)
        assert cmd_loop(args) == 0
        out = capsys.readouterr().out
        assert "cycle 1:" in out
        assert "cycle 2:" in out
        assert "stopped: max_cycles" in out

        spath = state_path(loops_dir(load_manifest(operator_layer), operator_layer), "deliver")
        state = load_loop_state(spath, "deliver")
        assert state.cycle == 2
        assert state.status == "stopped"
