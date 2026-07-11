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
            name="deliver", engine=None, concurrency=0, status=True, reset=False, json=False
        )
        assert cmd_cycle(args) == 0
        out = capsys.readouterr().out
        # Human-readable by default (the uniform convention): name + status appear.
        assert "deliver" in out
        assert "pending" in out  # a never-run loop reports "pending"

    def test_status_json(self, operator_layer: Path, monkeypatch, capsys) -> None:
        from alc.cli import cmd_cycle

        _write_loop(operator_layer, "deliver", _LOOP_MODE_B)
        _chdir_to_project(operator_layer, monkeypatch)

        args = argparse.Namespace(
            name="deliver", engine=None, concurrency=0, status=True, reset=False, json=True
        )
        assert cmd_cycle(args) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["name"] == "deliver"
        assert out["status"] == "pending"
        assert out["cycle"] == 0

    def test_reset_then_runs_one_cycle(self, operator_layer: Path, monkeypatch, capsys) -> None:
        from alc.cli import cmd_cycle

        _write_loop(operator_layer, "deliver", _LOOP_MODE_B)
        _seed_queue(operator_layer, "t1")
        _chdir_to_project(operator_layer, monkeypatch)

        # Pre-write a stopped state at cycle 9 to prove --reset clears it AND runs.
        spath = state_path(loops_dir(load_manifest(operator_layer), operator_layer), "deliver")
        spath.parent.mkdir(parents=True, exist_ok=True)
        spath.write_text(
            LoopState(name="deliver", status="stopped", cycle=9, stopped_reason="max_cycles")
            .model_dump_json()
        )

        args = argparse.Namespace(
            name="deliver", engine="mock", concurrency=0, status=False, reset=True
        )
        assert cmd_cycle(args) == 0
        out = capsys.readouterr().out
        # It announced the reset AND ran a fresh cycle (not the reset-only no-op).
        assert "reset" in out.lower()
        assert "cycle 1:" in out
        reloaded = load_loop_state(spath, "deliver")
        # Started from a fresh state (cycle 0), then ran exactly one cycle.
        assert reloaded.cycle == 1

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


# ---------------------------------------------------------------------------
# Replenish header (observability)
# ---------------------------------------------------------------------------


class TestReplenishHeader:
    """The replenish step must print a ▶ header to stderr (Mode A only)."""

    def _setup_specialist_loop(
        self, operator_layer: Path, monkeypatch
    ) -> tuple:
        """Wire up a specialist-replenish loop with a fake run_specialist."""
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

        def _fake_run_specialist(
            *, manifest, operator_layer, specialist, task, engine_override
        ):
            from alc.models import RunReport, Scorecard, SpecialistReport

            act = RunReport(
                blueprint="chore",
                engine="mock",
                success=True,
                attempts=[],
                scorecard=Scorecard(span=0, passes=0, streak=0, touch=0),
                output_text="",
            )
            return SpecialistReport(
                specialist=specialist.name, act=act, knowledge_updated=False
            )

        monkeypatch.setattr("alc.specialist.run_specialist", _fake_run_specialist)

        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        return manifest, loop_def

    def test_specialist_replenish_prints_header(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        """Mode A specialist replenish emits '▶ replenish — specialist:<ref>'."""
        from alc import loop as loop_mod

        manifest, loop_def = self._setup_specialist_loop(operator_layer, monkeypatch)
        loop_mod.run_replenish(manifest, operator_layer, loop_def, engine_override="mock")

        err = capsys.readouterr().err
        assert any(
            line.startswith("▶ replenish — specialist:") and "pm" in line
            for line in err.splitlines()
        ), f"Expected replenish header in stderr, got: {err!r}"

    def test_mode_b_prints_no_replenish_header(
        self, operator_layer: Path, capsys
    ) -> None:
        """Mode B (no replenish configured) must not emit any '▶ replenish' line."""
        from alc import loop as loop_mod

        manifest = load_manifest(operator_layer)
        _write_loop(operator_layer, "deliver", _LOOP_MODE_B)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")

        loop_mod.run_replenish(manifest, operator_layer, loop_def, engine_override="mock")

        err = capsys.readouterr().err
        assert "▶ replenish" not in err, f"Unexpected replenish header in stderr: {err!r}"


# ---------------------------------------------------------------------------
# Flow replenish (kind: flow)
# ---------------------------------------------------------------------------


class TestFlowReplenish:
    """Tests for run_replenish with kind: flow."""

    # A one-stage flow that uses the 'chore' blueprint (always passes its check).
    _PLAN_FLOW_YAML = (
        "name: plan\n"
        "description: Planning flow used as a replenish target.\n"
        "stages:\n"
        "  - name: make-plan\n"
        "    blueprint: chore\n"
    )

    def _write_plan_flow(self, operator_layer: Path) -> None:
        """Write a 'plan' flow YAML into the flows directory."""
        (operator_layer / "flows" / "plan.yaml").write_text(self._PLAN_FLOW_YAML)

    def _write_flow_replenish_loop(self, operator_layer: Path) -> None:
        """Write a loop definition whose replenish is kind: flow, ref: plan."""
        _write_loop(
            operator_layer,
            "deliver",
            "name: deliver\nreplenish:\n  kind: flow\n  ref: plan\n  task: build the plan\n"
            "stop:\n  max_cycles: 20\n",
        )

    def test_flow_replenish_prints_header(
        self, operator_layer: Path, capsys
    ) -> None:
        """run_replenish with kind:flow must print '▶ replenish — flow:<ref>' to stderr."""
        from alc import loop as loop_mod

        self._write_plan_flow(operator_layer)
        self._write_flow_replenish_loop(operator_layer)

        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")

        loop_mod.run_replenish(manifest, operator_layer, loop_def, engine_override="mock")

        err = capsys.readouterr().err
        assert any(
            line.startswith("▶ replenish — flow:") and "plan" in line
            for line in err.splitlines()
        ), f"Expected '▶ replenish — flow:plan' in stderr, got: {err!r}"

    def test_flow_replenish_dispatches_to_flow_runner(
        self, operator_layer: Path
    ) -> None:
        """run_replenish with kind:flow must invoke FlowRunner and return a non-zero engine_calls delta."""
        from alc import loop as loop_mod

        self._write_plan_flow(operator_layer)
        self._write_flow_replenish_loop(operator_layer)

        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")

        _enqueued, delta = loop_mod.run_replenish(
            manifest, operator_layer, loop_def, engine_override="mock"
        )
        # The chore blueprint has one 'true' check; MockEngine runs one attempt.
        assert delta["engine_calls"] >= 1, (
            f"Expected engine_calls > 0 from the flow run, got delta={delta}"
        )

    def test_flow_replenish_via_mock_flow_runner(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        """FlowRunner is called with correct args; returned FlowReport is folded into delta."""
        from alc import loop as loop_mod
        from alc.models import FlowReport, RunReport, Scorecard, AttemptRecord

        self._write_plan_flow(operator_layer)
        self._write_flow_replenish_loop(operator_layer)

        # Build a synthetic FlowReport with one stage that had one engine attempt.
        _fake_stage = RunReport(
            blueprint="chore",
            engine="mock",
            success=True,
            attempts=[AttemptRecord(index=0, engine_ok=True, failed_checks=[])],
            scorecard=Scorecard(span=1, passes=1, streak=1, touch=0),
            output_text="done",
        )
        _fake_report = FlowReport(
            flow="plan",
            engine="mock",
            success=True,
            stages=[_fake_stage],
            scorecard=Scorecard(span=1, passes=1, streak=1, touch=0),
        )

        # Capture the arguments passed to FlowRunner.run.
        calls: list[dict] = []

        class _MockFlowRunner:
            def __init__(self, *, manifest, operator_layer):
                self._manifest = manifest
                self._operator_layer = operator_layer

            def run(self, flow, *, task, engine_override, workdir):
                calls.append(
                    {"flow_name": flow.name, "task": task, "engine_override": engine_override}
                )
                return _fake_report

        monkeypatch.setattr("alc.flow.FlowRunner", _MockFlowRunner)

        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")

        _enqueued, delta = loop_mod.run_replenish(
            manifest, operator_layer, loop_def, engine_override="mock"
        )

        # FlowRunner.run was called with the right flow name and task.
        assert len(calls) == 1
        assert calls[0]["flow_name"] == "plan"
        assert calls[0]["task"] == "build the plan"
        assert calls[0]["engine_override"] == "mock"

        # Budget delta reflects the one engine attempt in the fake report.
        assert delta["engine_calls"] == 1

        # Header was printed.
        err = capsys.readouterr().err
        assert "▶ replenish — flow:plan" in err

    def test_flow_replenish_engine_calls_folded_into_cycle_delta(
        self, operator_layer: Path
    ) -> None:
        """run_cycle with a flow replenish accumulates engine_calls in the cycle budget_delta."""
        from alc.models import LoopState

        self._write_plan_flow(operator_layer)
        self._write_flow_replenish_loop(operator_layer)
        # Seed a queue task so the cycle makes progress and does not stop on no_new_work.
        _seed_queue(operator_layer, "t1")

        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        _new_state, record = run_cycle(
            manifest, operator_layer, loop_def, LoopState(name="deliver"), engine_override="mock"
        )
        # The plan flow ran (>= 1 engine call) + the drained ship flow ran (>= 2).
        assert record.budget_delta["engine_calls"] >= 2


class TestFlowReplenishValidation:
    """validate_loop must reject a flow replenish whose flow file is missing."""

    def test_missing_flow_ref_yields_error_violation(
        self, operator_layer: Path
    ) -> None:
        """kind:flow with a ref that has no corresponding YAML -> error violation."""
        from alc.policy import validate_loop
        from alc.models import LoopDefinition

        loop_def = LoopDefinition.model_validate(
            {
                "name": "bad-loop",
                "replenish": {"kind": "flow", "ref": "nonexistent", "task": "plan"},
                "stop": {"max_cycles": 5},
            }
        )
        manifest = load_manifest(operator_layer)
        violations = validate_loop(manifest, operator_layer, loop_def)
        error_rules = [v.rule for v in violations if v.severity == "error"]
        assert "loop-replenish-flow-exists" in error_rules, (
            f"Expected 'loop-replenish-flow-exists' error, got violations: {violations}"
        )

    def test_existing_flow_ref_no_violation(
        self, operator_layer: Path
    ) -> None:
        """kind:flow with a ref that resolves to an existing file -> no violation."""
        from alc.policy import validate_loop
        from alc.models import LoopDefinition

        # The 'ship' flow already exists in the operator_layer fixture.
        loop_def = LoopDefinition.model_validate(
            {
                "name": "ok-loop",
                "replenish": {"kind": "flow", "ref": "ship", "task": "plan"},
                "stop": {"max_cycles": 5},
            }
        )
        manifest = load_manifest(operator_layer)
        violations = validate_loop(manifest, operator_layer, loop_def)
        error_rules = [v.rule for v in violations if v.severity == "error"]
        assert "loop-replenish-flow-exists" not in error_rules

    def test_flow_kind_ref_required_at_model_level(self) -> None:
        """Replenish with kind:flow and no ref must raise ValidationError."""
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="ref"):
            from alc.models import Replenish
            Replenish(kind="flow", ref=None, task="plan")


# ---------------------------------------------------------------------------
# Plan replenish (kind: plan) — run a planner Specialist, then reuse the
# Conductor's parse + enqueue on the structured plan it returns.
# ---------------------------------------------------------------------------


def _init_git_repo(repo: Path) -> None:
    """Initialize a git repo with committed identity config inside *repo*."""
    import subprocess

    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@alc.local"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "ALC Test"],
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("seed\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "seed"],
        check=True,
        capture_output=True,
    )


class TestPlanReplenish:
    """run_replenish with kind: plan runs a planner Specialist, commits its roadmap
    change, then reuses the Conductor's parse_plan + dispatch_enqueue."""

    def _write_pm(self, operator_layer: Path) -> None:
        """Write a 'pm' planner Specialist definition."""
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

    def _write_demand_flow(self, operator_layer: Path) -> None:
        """Write a 'demand' flow so the catalog contains it (validated by parse_plan)."""
        (operator_layer / "flows" / "demand.yaml").write_text(
            "name: demand\n"
            "description: A unit of demand work.\n"
            "stages:\n"
            "  - name: build\n"
            "    blueprint: chore\n"
        )

    def _write_plan_replenish_loop(self, operator_layer: Path) -> None:
        """Write a loop definition whose replenish is kind: plan, ref: pm."""
        _write_loop(
            operator_layer,
            "deliver",
            "name: deliver\nreplenish:\n  kind: plan\n  ref: pm\n  task: plan next\n"
            "stop:\n  max_cycles: 20\n",
        )

    def _fake_planner(self, output_text: str, monkeypatch, success: bool = True) -> dict:
        """Patch run_specialist so the planner writes a roadmap file and returns
        the given output_text as its Act output (the structured plan).

        ``success`` sets the Act's success flag — pass False to simulate a planner
        whose engine turn failed (e.g. a 503/quota error).

        Returns a dict that captures the output_contract the plan branch injected
        into the Act call (under key "output_contract"), so tests can assert the
        plan contract reached the planner directive.
        """
        captured: dict = {}

        def _run(
            *,
            manifest,
            operator_layer,
            specialist,
            task,
            engine_override,
            workdir,
            output_contract=None,
        ):
            from alc.models import RunReport, Scorecard, SpecialistReport

            captured["output_contract"] = output_contract
            # Simulate the planner touching the roadmap so there is something to commit.
            docs = operator_layer.parent / "docs"
            docs.mkdir(parents=True, exist_ok=True)
            (docs / "ROADMAP.md").write_text("# Roadmap\n- next version\n")
            act = RunReport(
                blueprint="chore",
                engine="mock",
                success=success,
                attempts=[],
                scorecard=Scorecard(span=0, passes=0, streak=0, touch=0),
                output_text=output_text,
            )
            return SpecialistReport(
                specialist=specialist.name, act=act, knowledge_updated=False
            )

        monkeypatch.setattr("alc.specialist.run_specialist", _run)
        return captured

    def test_act_failure_skips_enqueue(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        """When the planner's Act FAILS (engine/API error), the branch must NOT try
        to parse/heal or hammer the engine — a clean no-op, 0 enqueued."""
        from alc import loop as loop_mod

        _init_git_repo(operator_layer.parent)
        self._write_pm(operator_layer)
        self._write_demand_flow(operator_layer)
        self._write_plan_replenish_loop(operator_layer)
        # A perfectly VALID plan output, but the Act failed -> it must be ignored.
        self._fake_planner(
            '[{"kind":"flow","name":"demand","task":"T\\n\\nd"}]',
            monkeypatch,
            success=False,
        )

        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        enqueued, _delta = loop_mod.run_replenish(
            manifest, operator_layer, loop_def, engine_override="mock"
        )

        assert enqueued == 0
        queue_dir = operator_layer.parent / manifest.queue_dir
        assert not list(queue_dir.glob("*.yaml"))
        assert "planner Act failed" in capsys.readouterr().err

    def test_plan_replenish_prints_header(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        """run_replenish with kind:plan must print '▶ replenish — plan:<ref>'."""
        from alc import loop as loop_mod

        _init_git_repo(operator_layer.parent)
        self._write_pm(operator_layer)
        self._write_demand_flow(operator_layer)
        self._write_plan_replenish_loop(operator_layer)
        self._fake_planner(
            '[{"kind":"flow","name":"demand","task":"A\\n\\nx"}]', monkeypatch
        )

        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        loop_mod.run_replenish(manifest, operator_layer, loop_def, engine_override="mock")

        err = capsys.readouterr().err
        assert any(
            line.startswith("▶ replenish — plan:") and "pm" in line
            for line in err.splitlines()
        ), f"Expected '▶ replenish — plan:pm' in stderr, got: {err!r}"

    def test_happy_path_enqueues_demands_and_commits_roadmap(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        """A valid Conductor plan -> the roadmap change is committed and N demand
        tasks are written (each flow==demand, isolate false, title == first line)."""
        import subprocess

        from alc import loop as loop_mod
        from alc.models import QueueTask

        _init_git_repo(operator_layer.parent)
        self._write_pm(operator_layer)
        self._write_demand_flow(operator_layer)
        self._write_plan_replenish_loop(operator_layer)
        plan_json = (
            '[{"kind":"flow","name":"demand","task":"First title\\n\\ndetails one"},'
            '{"kind":"flow","name":"demand","task":"Second title\\n\\ndetails two"}]'
        )
        self._fake_planner(plan_json, monkeypatch)

        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        enqueued, delta = loop_mod.run_replenish(
            manifest, operator_layer, loop_def, engine_override="mock"
        )

        assert enqueued == 2

        # The roadmap change was committed (tree is clean for the demand guard).
        status = subprocess.run(
            ["git", "-C", str(operator_layer.parent), "status", "--porcelain"],
            capture_output=True,
            text=True,
        )
        assert (operator_layer.parent / "docs" / "ROADMAP.md").exists()
        assert "docs/ROADMAP.md" not in status.stdout

        # The commit was made under the roadmap message (not merely a clean tree).
        subjects = subprocess.run(
            ["git", "-C", str(operator_layer.parent), "log", "--format=%s"],
            capture_output=True,
            text=True,
        )
        assert "chore(roadmap): plan next version" in subjects.stdout.splitlines()

        # Each written task re-loads as a demand QueueTask, isolate false, short title.
        queue_dir = operator_layer.parent / manifest.queue_dir
        names = sorted(p.name for p in queue_dir.glob("*.yaml"))
        # The queue filename is descriptive (prefix + title slug), not an opaque uid,
        # so the drain header `▶ <file> — flow:demand` reads meaningfully.
        assert names[0].startswith("plan-000-first-title-")
        assert names[1].startswith("plan-001-second-title-")
        tasks = [
            QueueTask.model_validate(yaml.safe_load((queue_dir / n).read_text()))
            for n in names
        ]
        assert len(tasks) == 2
        titles = [t.task.splitlines()[0] for t in tasks]
        assert titles == ["First title", "Second title"]
        for t in tasks:
            assert t.flow == "demand"
            assert t.isolate is False

    def test_concurrent_drain_enqueues_isolated_demands(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        """When the loop drains concurrently (drain.concurrency > 1), demands are
        enqueued isolate:true so each committing demand runs in its own worktree
        (the parallel-demands path). concurrency 1 stays isolate:false (the sibling
        happy-path test)."""
        from alc import loop as loop_mod
        from alc.models import QueueTask

        _init_git_repo(operator_layer.parent)
        self._write_pm(operator_layer)
        self._write_demand_flow(operator_layer)
        # A plan-replenish loop whose drain runs 3 demands in parallel.
        _write_loop(
            operator_layer,
            "deliver",
            "name: deliver\nreplenish:\n  kind: plan\n  ref: pm\n  task: plan next\n"
            "drain:\n  concurrency: 3\nstop:\n  max_cycles: 20\n",
        )
        self._fake_planner(
            '[{"kind":"flow","name":"demand","task":"First\\n\\na"},'
            '{"kind":"flow","name":"demand","task":"Second\\n\\nb"}]',
            monkeypatch,
        )

        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        assert loop_def.drain.concurrency == 3
        enqueued, _delta = loop_mod.run_replenish(
            manifest, operator_layer, loop_def, engine_override="mock"
        )

        assert enqueued == 2
        queue_dir = operator_layer.parent / manifest.queue_dir
        tasks = [
            QueueTask.model_validate(yaml.safe_load(p.read_text()))
            for p in sorted(queue_dir.glob("*.yaml"))
        ]
        assert len(tasks) == 2
        for t in tasks:
            assert t.flow == "demand"
            assert t.isolate is True

    def test_no_op_when_plan_invalid(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        """A planner whose output is not valid JSON -> 0 tasks, no exception escapes."""
        from alc import loop as loop_mod

        _init_git_repo(operator_layer.parent)
        self._write_pm(operator_layer)
        self._write_demand_flow(operator_layer)
        self._write_plan_replenish_loop(operator_layer)
        self._fake_planner("this is not a plan", monkeypatch)

        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        enqueued, _delta = loop_mod.run_replenish(
            manifest, operator_layer, loop_def, engine_override="mock"
        )

        assert enqueued == 0
        queue_dir = operator_layer.parent / manifest.queue_dir
        assert not list(queue_dir.glob("*.yaml"))
        err = capsys.readouterr().err
        assert "plan not enqueued" in err

    def test_no_op_when_unknown_flow(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        """A plan referencing a flow not in the catalog -> clean no-op (0 tasks)."""
        from alc import loop as loop_mod

        _init_git_repo(operator_layer.parent)
        self._write_pm(operator_layer)
        self._write_demand_flow(operator_layer)
        self._write_plan_replenish_loop(operator_layer)
        # 'nope' is not a flow in the catalog -> parse_plan raises ValueError.
        # Force the corrective engine to also fail so this stays a clean no-op.
        self._patch_corrective_engine("still bad", monkeypatch)
        self._fake_planner(
            '[{"kind":"flow","name":"nope","task":"X\\n\\ny"}]', monkeypatch
        )

        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        enqueued, _delta = loop_mod.run_replenish(
            manifest, operator_layer, loop_def, engine_override="mock"
        )

        assert enqueued == 0
        queue_dir = operator_layer.parent / manifest.queue_dir
        assert not list(queue_dir.glob("*.yaml"))

    def _patch_corrective_engine(self, output_text: str, monkeypatch) -> None:
        """Patch resolve_engine so finalize_plan's corrective turn returns output_text.

        The plan branch resolves the corrective engine via
        alc.engines.registry.resolve_engine; a MockEngine with a fixed output lets a
        test script whether the reformat turn heals (valid JSON) or fails (bad text).
        """
        from alc.engines.mock import MockEngine as _MockEngine

        def _resolve(name, engines):
            return _MockEngine(output=output_text)

        monkeypatch.setattr("alc.engines.registry.resolve_engine", _resolve)

    def test_self_heals_malformed_first_output(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        """First planner output is malformed but the corrective turn is valid ->
        the demands enqueue and the roadmap is committed (self-heal)."""
        import subprocess

        from alc import loop as loop_mod

        _init_git_repo(operator_layer.parent)
        self._write_pm(operator_layer)
        self._write_demand_flow(operator_layer)
        self._write_plan_replenish_loop(operator_layer)
        # The corrective engine turn returns two valid demands.
        self._patch_corrective_engine(
            '[{"kind":"flow","name":"demand","task":"A\\n\\nx"},'
            '{"kind":"flow","name":"demand","task":"B\\n\\ny"}]',
            monkeypatch,
        )
        # The planner's FIRST output is illegal JSON (a bare \' as dogfood hit).
        self._fake_planner("[{'kind': 'flow'}]", monkeypatch)

        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        enqueued, _delta = loop_mod.run_replenish(
            manifest, operator_layer, loop_def, engine_override="mock"
        )

        assert enqueued == 2
        # The roadmap change was committed under its message (tree clean for demands).
        subjects = subprocess.run(
            ["git", "-C", str(operator_layer.parent), "log", "--format=%s"],
            capture_output=True,
            text=True,
        )
        assert "chore(roadmap): plan next version" in subjects.stdout.splitlines()

    def test_no_op_when_unrecoverable_through_retries(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        """Malformed through the first output and every corrective retry -> 0
        enqueued, no exception escapes (clean no-op)."""
        from alc import loop as loop_mod

        _init_git_repo(operator_layer.parent)
        self._write_pm(operator_layer)
        self._write_demand_flow(operator_layer)
        self._write_plan_replenish_loop(operator_layer)
        self._patch_corrective_engine("still not json", monkeypatch)
        self._fake_planner("neither is this", monkeypatch)

        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        enqueued, _delta = loop_mod.run_replenish(
            manifest, operator_layer, loop_def, engine_override="mock"
        )

        assert enqueued == 0
        queue_dir = operator_layer.parent / manifest.queue_dir
        assert not list(queue_dir.glob("*.yaml"))
        assert "plan not enqueued" in capsys.readouterr().err

    def test_valid_first_output_injects_contract_no_corrective(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        """A valid first output enqueues with NO corrective turn, and the planner's
        Act directive carried the injected plan contract."""
        from alc import loop as loop_mod

        _init_git_repo(operator_layer.parent)
        self._write_pm(operator_layer)
        self._write_demand_flow(operator_layer)
        self._write_plan_replenish_loop(operator_layer)
        # If a corrective turn ran it would call this engine; make it fail loudly so
        # a spurious retry would corrupt the (already-valid) plan and fail the test.
        self._patch_corrective_engine("must-not-be-used", monkeypatch)
        captured = self._fake_planner(
            '[{"kind":"flow","name":"demand","task":"A\\n\\nx"}]', monkeypatch
        )

        manifest = load_manifest(operator_layer)
        loop_def = load_loop(loops_dir(manifest, operator_layer), "deliver")
        enqueued, _delta = loop_mod.run_replenish(
            manifest, operator_layer, loop_def, engine_override="mock"
        )

        assert enqueued == 1
        # The plan contract was injected into the planner's Act directive.
        contract = captured["output_contract"]
        assert contract is not None
        assert "JSON array" in contract
        assert "demand (flow)" in contract  # the catalog was rendered in


class TestPlanReplenishValidation:
    """validate_loop and the model validator for kind: plan."""

    def test_missing_specialist_ref_yields_error_violation(
        self, operator_layer: Path
    ) -> None:
        """kind:plan with a ref that has no specialist YAML -> error violation."""
        from alc.policy import validate_loop

        loop_def = LoopDefinition.model_validate(
            {
                "name": "bad-loop",
                "replenish": {"kind": "plan", "ref": "nonexistent", "task": "plan"},
                "stop": {"max_cycles": 5},
            }
        )
        manifest = load_manifest(operator_layer)
        violations = validate_loop(manifest, operator_layer, loop_def)
        error_rules = [v.rule for v in violations if v.severity == "error"]
        assert "loop-replenish-specialist-exists" in error_rules, (
            f"Expected specialist-exists error, got violations: {violations}"
        )

    def test_existing_specialist_ref_no_violation(
        self, operator_layer: Path
    ) -> None:
        """kind:plan with a ref that resolves to an existing specialist -> no violation."""
        from alc.policy import validate_loop

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
        loop_def = LoopDefinition.model_validate(
            {
                "name": "ok-loop",
                "replenish": {"kind": "plan", "ref": "pm", "task": "plan"},
                "stop": {"max_cycles": 5},
            }
        )
        manifest = load_manifest(operator_layer)
        violations = validate_loop(manifest, operator_layer, loop_def)
        error_rules = [v.rule for v in violations if v.severity == "error"]
        assert "loop-replenish-specialist-exists" not in error_rules

    def test_plan_kind_ref_required_at_model_level(self) -> None:
        """Replenish with kind:plan and no ref must raise ValidationError."""
        from pydantic import ValidationError

        from alc.models import Replenish

        with pytest.raises(ValidationError, match="ref"):
            Replenish(kind="plan", ref=None, task="x")

    def test_plan_kind_with_ref_is_valid(self) -> None:
        """Replenish(kind='plan', ref='pm', task='x') is a valid model."""
        from alc.models import Replenish

        replenish = Replenish(kind="plan", ref="pm", task="x")
        assert replenish.kind == "plan"
        assert replenish.ref == "pm"


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
