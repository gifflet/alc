# test_events.py — Hermetic tests for the per-run event log (alc.events).
# Covers the emitter contract: unbound emit is a no-op, a bound log writes valid
# JSON lines, bindings are reentrant (outer wins), emission is best-effort (a bad
# path never raises), and new_run_log_path produces sortable, slug-safe names.
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from alc.events import bind_run_log, emit, new_run_log_path
from alc.flow import FlowRunner
from alc.intake import load_blueprint, load_flow, load_manifest
from alc.queue import process_queue
from alc.runner import MandateRunner


def _read_events(log: Path) -> list[dict]:
    """Parse a run-log file into a list of event dicts (one per line)."""
    return [json.loads(line) for line in log.read_text().splitlines()]


class TestEmitUnbound:
    def test_emit_without_binding_is_noop(self, tmp_path: Path) -> None:
        """Outside any binding, emit does nothing and never raises."""
        # No file is created and no exception is raised.
        emit("mandate_started", blueprint="chore")
        assert list(tmp_path.iterdir()) == []


class TestBindRunLog:
    def test_bind_creates_dirs_and_writes_json_lines(self, tmp_path: Path) -> None:
        """Binding creates parent dirs; each emit appends one valid JSON line."""
        log = tmp_path / "nested" / "deeper" / "run.jsonl"

        with bind_run_log(log):
            emit("mandate_started", blueprint="chore", engine="mock")
            emit("mandate_finished", success=True)

        assert log.exists()
        lines = log.read_text().splitlines()
        assert len(lines) == 2

        first = json.loads(lines[0])
        assert first["event"] == "mandate_started"
        assert first["blueprint"] == "chore"
        assert first["engine"] == "mock"
        # Every line carries an ISO-8601 UTC timestamp ending in Z.
        assert first["ts"].endswith("Z")
        # ts parses as a real timestamp once the Z is normalised.
        datetime.fromisoformat(first["ts"].replace("Z", "+00:00"))

        second = json.loads(lines[1])
        assert second["event"] == "mandate_finished"
        assert second["success"] is True

    def test_binding_unbinds_on_exit(self, tmp_path: Path) -> None:
        """After the context exits, emit is a no-op again (nothing appended)."""
        log = tmp_path / "run.jsonl"
        with bind_run_log(log):
            emit("mandate_started")
        emit("mandate_finished")  # no binding -> dropped

        lines = log.read_text().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["event"] == "mandate_started"


class TestReentrantBinding:
    def test_inner_binding_is_noop_outer_wins(self, tmp_path: Path) -> None:
        """A nested bind is a no-op: events land in the OUTERMOST log file."""
        outer = tmp_path / "outer.jsonl"
        inner = tmp_path / "inner.jsonl"

        with bind_run_log(outer):
            emit("task_started")
            with bind_run_log(inner):
                emit("flow_started")
                emit("mandate_started")
            emit("task_finished")

        # The inner file was never created — the outer binding won.
        assert not inner.exists()
        events = [json.loads(line)["event"] for line in outer.read_text().splitlines()]
        assert events == [
            "task_started",
            "flow_started",
            "mandate_started",
            "task_finished",
        ]


class TestBestEffort:
    def test_emit_swallows_io_errors(self, tmp_path: Path) -> None:
        """A binding whose path cannot be written must not crash emit."""
        # Bind to a path whose "parent" is actually a file -> writing fails.
        blocker = tmp_path / "blocker"
        blocker.write_text("x")
        bad_path = blocker / "run.jsonl"  # blocker is a file, not a dir

        # Neither bind nor emit may raise, even though I/O is impossible.
        with bind_run_log(bad_path):
            emit("mandate_started", blueprint="chore")

        assert blocker.read_text() == "x"

    def test_emit_swallows_serialisation_errors(self, tmp_path: Path) -> None:
        """A payload json cannot serialise natively degrades gracefully."""
        log = tmp_path / "run.jsonl"
        with bind_run_log(log):
            # A set is not JSON-serialisable; default=str keeps it best-effort.
            emit("weird", value={1, 2, 3})
        # The line was still written (stringified), and nothing raised.
        assert log.exists()
        assert json.loads(log.read_text().splitlines()[0])["event"] == "weird"


class TestNewRunLogPath:
    def test_name_structure_and_slug(self, tmp_path: Path) -> None:
        """The filename is <ts>-<kind>-<slug>-<hex6>.jsonl with a safe slug."""
        path = new_run_log_path(tmp_path, "run", "Tidy Up: The Changelog!")

        assert path.parent == tmp_path
        assert path.suffix == ".jsonl"
        stem = path.stem  # <ts>-run-tidy-up-the-changelog-<hex6>
        assert "-run-" in stem
        assert "tidy-up-the-changelog" in stem
        # No unsafe characters leaked into the slug.
        assert " " not in stem and ":" not in stem and "!" not in stem

    def test_paths_sort_by_time(self) -> None:
        """The UTC timestamp prefix makes paths lexicographically time-ordered."""
        base = Path("/runs")
        early = new_run_log_path(base, "run", "a")
        # A later timestamp string must sort after an earlier one; simulate by
        # comparing prefixes (both share the same call second here, so assert the
        # timestamp prefix is a sortable YYYYMMDDT string).
        ts_prefix = early.stem.split("-")[0]
        assert ts_prefix[:8].isdigit()
        assert ts_prefix[8] == "T"

    def test_empty_label_falls_back(self, tmp_path: Path) -> None:
        """An unusable label degrades to a stable fallback slug, never crashes."""
        path = new_run_log_path(tmp_path, "task", "!!!")
        assert path.suffix == ".jsonl"
        assert "-task-" in path.stem


class TestMandateIntegration:
    """A bound MandateRunner run records the full mandate event sequence."""

    def test_run_emits_mandate_act_verify_sequence(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        blueprint = load_blueprint(
            operator_layer.parent / manifest.blueprints_dir, "chore"
        )
        runner = MandateRunner(manifest=manifest, operator_layer=operator_layer)

        log = new_run_log_path(
            operator_layer.parent / manifest.runs_dir, "run", "chore tidy"
        )
        with bind_run_log(log):
            report = runner.run(
                blueprint=blueprint, task="tidy imports", engine_override="mock"
            )

        assert report.success is True
        events = _read_events(log)
        names = [e["event"] for e in events]
        assert names == [
            "mandate_started",
            "act_started",
            "act_finished",
            "verify_started",
            "check_finished",
            "mandate_finished",
        ]

        started = events[0]
        assert started["blueprint"] == "chore"
        assert started["task"] == "tidy imports"
        assert started["engine"] == "mock"

        finished = events[-1]
        assert finished["success"] is True
        assert set(finished["scorecard"]) == {"span", "passes", "streak", "touch"}

        # The single "smoke" check appears as a passing check_finished.
        check = next(e for e in events if e["event"] == "check_finished")
        assert check["name"] == "smoke"
        assert check["passed"] is True
        assert "output_tail" in check


class TestFlowIntegration:
    """A bound flow run brackets its stages' mandate events."""

    def test_flow_emits_flow_and_stage_events(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        flow = load_flow(operator_layer.parent / manifest.flows_dir, "ship")
        runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)

        log = new_run_log_path(
            operator_layer.parent / manifest.runs_dir, "flow", "ship tidy"
        )
        with bind_run_log(log):
            report = runner.run(
                flow=flow, task="tidy the changelog", engine_override="mock"
            )

        assert report.success is True
        names = [e["event"] for e in _read_events(log)]

        # The flow brackets everything; two stages each nest a full mandate.
        assert names[0] == "flow_started"
        assert names[-1] == "flow_finished"
        assert names.count("stage_started") == 2
        assert names.count("stage_finished") == 2
        assert names.count("mandate_started") == 2
        # A stage's mandate events fall between its stage_started/stage_finished.
        assert names.index("mandate_started") > names.index("stage_started")


class TestTickIntegration:
    """A tick binds ONE run log per task; the flow's events nest inside it."""

    def test_tick_task_wraps_flow_events(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)

        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "t1.yaml").write_text(
            'flow: ship\ntask: "tidy"\nengine: mock\nisolate: false\n'
        )

        results = process_queue(manifest, operator_layer)
        assert len(results) == 1 and results[0].success is True

        runs_dir = operator_layer.parent / manifest.runs_dir
        logs = list(runs_dir.glob("*.jsonl"))
        assert len(logs) == 1, "the task must produce exactly one run log"

        events = _read_events(logs[0])
        names = [e["event"] for e in events]

        # The task brackets the whole run; the flow's events nest inside it.
        assert names[0] == "task_started"
        assert names[-1] == "task_finished"
        assert "flow_started" in names
        assert "mandate_started" in names

        started = events[0]
        assert started["task_file"] == "t1.yaml"
        assert started["name"] == "ship"
        assert started["kind"] == "flow"
        assert started["isolate"] is False

        finished = events[-1]
        assert finished["success"] is True


class TestConductSerialIntegration:
    """Serial conduct dispatch binds ONE run log per unit (parity with fanout)."""

    def test_dispatch_now_emits_per_unit_run_log(self, operator_layer: Path) -> None:
        from alc.conduct import dispatch_now
        from alc.models import ConductorPlan, PlannedUnit

        manifest = load_manifest(operator_layer)
        plan = ConductorPlan(items=[PlannedUnit(kind="flow", name="ship", task="tidy")])

        reports = dispatch_now(plan, manifest, operator_layer, engine_override="mock")
        assert len(reports) == 1 and reports[0].success is True

        runs_dir = operator_layer.parent / manifest.runs_dir
        logs = list(runs_dir.glob("*.jsonl"))
        assert len(logs) == 1, "the serial unit must produce exactly one run log"
        assert "-unit-" in logs[0].name

        names = [e["event"] for e in _read_events(logs[0])]
        assert names[0] == "flow_started"
        assert "mandate_started" in names
        assert names[-1] == "flow_finished"


class TestCycleReplenishIntegration:
    """A loop's replenish step (a direct flow run) is observable via a run log."""

    def test_replenish_flow_emits_run_log(self, operator_layer: Path) -> None:
        from alc.loop import run_replenish
        from alc.models import LoopDefinition, LoopStop, Replenish

        manifest = load_manifest(operator_layer)
        loop_def = LoopDefinition(
            name="demo",
            replenish=Replenish(kind="flow", ref="ship", task="plan next"),
            stop=LoopStop(max_cycles=1),
        )

        run_replenish(manifest, operator_layer, loop_def, engine_override="mock")

        runs_dir = operator_layer.parent / manifest.runs_dir
        logs = list(runs_dir.glob("*.jsonl"))
        assert len(logs) == 1, "the replenish flow must produce exactly one run log"
        assert "-replenish-" in logs[0].name

        names = [e["event"] for e in _read_events(logs[0])]
        assert names[0] == "flow_started"
        assert names[-1] == "flow_finished"
