# test_conduct.py — Hermetic tests for the Conductor: parse_plan, plan_flows,
# dispatch_enqueue, dispatch_now. No real engine is ever called.
from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from alc.conduct import conduct, dispatch_enqueue, dispatch_now, parse_plan, plan_flows
from alc.engines.mock import MockEngine
from alc.intake import load_manifest
from alc.models import ConductorPlan, PlannedUnit, QueueTask


# ---------------------------------------------------------------------------
# parse_plan — pure unit tests (no fixtures needed)
# ---------------------------------------------------------------------------


class TestParsePlanValid:
    def test_returns_single_item(self) -> None:
        plan = parse_plan('[{"flow":"ship","task":"x"}]', {"ship"})
        assert isinstance(plan, ConductorPlan)
        assert len(plan.items) == 1
        assert plan.items[0].flow == "ship"
        assert plan.items[0].task == "x"

    def test_returns_multiple_items(self) -> None:
        raw = '[{"flow":"ship","task":"first"},{"flow":"ship","task":"second"}]'
        plan = parse_plan(raw, {"ship"})
        assert len(plan.items) == 2


class TestParsePlanExtractsFencedJson:
    def test_markdown_fenced_code_block(self) -> None:
        fenced = '```json\n[{"flow":"ship","task":"tidy"}]\n```'
        plan = parse_plan(fenced, {"ship"})
        assert len(plan.items) == 1
        assert plan.items[0].flow == "ship"

    def test_prose_surrounding_array(self) -> None:
        text = 'Here is the plan:\n[{"flow":"ship","task":"tidy"}]\nEnd.'
        plan = parse_plan(text, {"ship"})
        assert len(plan.items) == 1


class TestParsePlanUnknownFlowRaises:
    def test_raises_for_unknown_flow(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="unknown flow"):
            parse_plan('[{"flow":"does-not-exist","task":"x"}]', {"ship"})


class TestParsePlanMalformedRaises:
    def test_raises_for_non_json(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            parse_plan("not json at all", {"ship"})

    def test_raises_for_object_not_array(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="JSON array"):
            parse_plan('{"flow":"ship","task":"x"}', {"ship"})

    def test_raises_for_item_missing_task_key(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="missing"):
            parse_plan('[{"flow":"ship"}]', {"ship"})


# ---------------------------------------------------------------------------
# plan_flows — uses MockEngine with a canned output
# ---------------------------------------------------------------------------


class TestPlanFlowsHappyPath:
    def test_returns_conductor_plan(self) -> None:
        engine = MockEngine(output='[{"flow":"ship","task":"tidy"}]')
        plan = plan_flows(
            engine=engine,
            model=None,
            goal="do stuff",
            catalog_text="- ship: ships it (stages: plan, build)",
            available_flows={"ship"},
        )
        assert isinstance(plan, ConductorPlan)
        assert len(plan.items) == 1
        assert plan.items[0].flow == "ship"
        assert plan.items[0].task == "tidy"

    def test_retries_on_invalid_output_then_succeeds(self) -> None:
        """First call returns bad JSON; second call returns valid JSON after corrective suffix."""
        call_count = 0
        valid_output = '[{"flow":"ship","task":"tidy"}]'

        class _SequencedEngine:
            name = "mock"

            def capabilities(self):
                from alc.engine import Capabilities
                return Capabilities()

            def health_check(self) -> bool:
                return True

            def run(self, request):
                nonlocal call_count
                from alc.engine import EngineResult
                call_count += 1
                if call_count == 1:
                    return EngineResult(ok=True, output_text="not valid json")
                return EngineResult(ok=True, output_text=valid_output)

        plan = plan_flows(
            engine=_SequencedEngine(),  # type: ignore[arg-type]
            model=None,
            goal="do stuff",
            catalog_text="- ship: ...",
            available_flows={"ship"},
            max_retries=1,
        )
        assert call_count == 2
        assert plan.items[0].flow == "ship"

    def test_raises_after_exhausting_retries(self) -> None:
        import pytest

        engine = MockEngine(output="still not json")
        with pytest.raises(ValueError, match="valid plan"):
            plan_flows(
                engine=engine,
                model=None,
                goal="do stuff",
                catalog_text="- ship: ...",
                available_flows={"ship"},
                max_retries=1,
            )


# ---------------------------------------------------------------------------
# dispatch_enqueue — uses operator_layer fixture
# ---------------------------------------------------------------------------


class TestDispatchEnqueueWritesQueueTasks:
    def test_writes_two_files(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        plan = ConductorPlan(items=[
            PlannedUnit(kind="flow", name="ship", task="first"),
            PlannedUnit(kind="flow", name="ship", task="second"),
        ])

        files = dispatch_enqueue(plan, manifest, operator_layer)

        assert len(files) == 2
        queue_dir = operator_layer.parent / manifest.queue_dir
        for filename in files:
            fpath = queue_dir / filename
            assert fpath.exists(), f"Expected {fpath} to exist"

    def test_each_file_is_valid_queue_task(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        plan = ConductorPlan(items=[
            PlannedUnit(kind="flow", name="ship", task="alpha"),
            PlannedUnit(kind="flow", name="ship", task="beta"),
        ])

        files = dispatch_enqueue(plan, manifest, operator_layer)

        queue_dir = operator_layer.parent / manifest.queue_dir
        for filename, item in zip(files, plan.items):
            raw = yaml.safe_load((queue_dir / filename).read_text())
            # Must parse as a valid QueueTask.
            qt = QueueTask.model_validate(raw)
            assert qt.isolate is True
            assert qt.unit_name() == item.name
            assert qt.task == item.task

    def test_engine_override_written_when_set(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        plan = ConductorPlan(items=[PlannedUnit(kind="flow", name="ship", task="x")])

        files = dispatch_enqueue(plan, manifest, operator_layer, engine_override="mock")

        queue_dir = operator_layer.parent / manifest.queue_dir
        raw = yaml.safe_load((queue_dir / files[0]).read_text())
        assert raw["engine"] == "mock"

    def test_no_engine_field_when_override_is_none(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        plan = ConductorPlan(items=[PlannedUnit(kind="flow", name="ship", task="x")])

        files = dispatch_enqueue(plan, manifest, operator_layer, engine_override=None)

        queue_dir = operator_layer.parent / manifest.queue_dir
        raw = yaml.safe_load((queue_dir / files[0]).read_text())
        assert "engine" not in raw


# ---------------------------------------------------------------------------
# dispatch_now — uses operator_layer fixture
# ---------------------------------------------------------------------------


class TestDispatchNowRunsFlows:
    def test_single_item_returns_one_flow_report(self, operator_layer: Path) -> None:
        from alc.models import FlowReport

        manifest = load_manifest(operator_layer)
        plan = ConductorPlan(items=[PlannedUnit(kind="flow", name="ship", task="tidy")])

        reports = dispatch_now(plan, manifest, operator_layer, engine_override="mock")

        assert len(reports) == 1
        report = reports[0]
        assert isinstance(report, FlowReport)
        assert report.success is True
        assert report.flow == "ship"


# ---------------------------------------------------------------------------
# Specialist routing helpers
# ---------------------------------------------------------------------------


def _write_specialist(operator_layer: Path, name: str = "db") -> None:
    """Write a specialist yaml whose Act blueprint is the fixture's chore blueprint."""
    specialists_dir = operator_layer / "specialists"
    specialists_dir.mkdir(exist_ok=True)
    data = {
        "name": name,
        "area": "the database access layer",
        "blueprint": "chore",
        "knowledge_path": f".alc/specialists/{name}.knowledge.md",
    }
    (specialists_dir / f"{name}.yaml").write_text(yaml.safe_dump(data))


# ---------------------------------------------------------------------------
# parse_plan — new (kind/name) shape and legacy shape
# ---------------------------------------------------------------------------


class TestParsePlanUnitShapes:
    def test_accepts_specialist_kind(self) -> None:
        raw = '[{"kind":"specialist","name":"db","task":"document"}]'
        plan = parse_plan(raw, {"ship"}, {"db"})
        assert len(plan.items) == 1
        assert plan.items[0].kind == "specialist"
        assert plan.items[0].name == "db"
        assert plan.items[0].task == "document"

    def test_accepts_flow_kind(self) -> None:
        raw = '[{"kind":"flow","name":"ship","task":"build it"}]'
        plan = parse_plan(raw, {"ship"}, {"db"})
        assert plan.items[0].kind == "flow"
        assert plan.items[0].name == "ship"

    def test_accepts_legacy_flow_shape(self) -> None:
        raw = '[{"flow":"ship","task":"tidy"}]'
        plan = parse_plan(raw, {"ship"}, {"db"})
        assert plan.items[0].kind == "flow"
        assert plan.items[0].name == "ship"

    def test_accepts_mixed_plan(self) -> None:
        raw = (
            '[{"kind":"flow","name":"ship","task":"a"},'
            '{"kind":"specialist","name":"db","task":"b"}]'
        )
        plan = parse_plan(raw, {"ship"}, {"db"})
        assert [i.kind for i in plan.items] == ["flow", "specialist"]

    def test_raises_for_unknown_specialist(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="unknown specialist"):
            parse_plan('[{"kind":"specialist","name":"nope","task":"x"}]', {"ship"}, {"db"})


# ---------------------------------------------------------------------------
# plan_flows — mixed plan driven by MockEngine(output=...)
# ---------------------------------------------------------------------------


class TestPlanFlowsMixed:
    def test_returns_mixed_plan(self) -> None:
        output = (
            '[{"kind":"flow","name":"ship","task":"build"},'
            '{"kind":"specialist","name":"db","task":"document"}]'
        )
        engine = MockEngine(output=output)
        plan = plan_flows(
            engine=engine,
            model=None,
            goal="do stuff",
            catalog_text="- ship (flow): ...\n- db (specialist): the db layer",
            available_flows={"ship"},
            available_specialists={"db"},
        )
        assert len(plan.items) == 2
        assert plan.items[0].kind == "flow"
        assert plan.items[1].kind == "specialist"
        assert plan.items[1].name == "db"


# ---------------------------------------------------------------------------
# dispatch_now — routes a specialist item to run_specialist
# ---------------------------------------------------------------------------


class TestDispatchNowRoutesSpecialist:
    def test_specialist_item_runs_and_writes_knowledge(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        _write_specialist(operator_layer, "db")
        plan = ConductorPlan(
            items=[PlannedUnit(kind="specialist", name="db", task="document the area")]
        )

        reports = dispatch_now(plan, manifest, operator_layer, engine_override="mock")

        # No FlowReport is produced for a specialist item.
        assert reports == []

        # The Knowledge File was written by the successful Act -> Learn cycle.
        knowledge_file = operator_layer.parent / ".alc/specialists/db.knowledge.md"
        assert knowledge_file.exists()


# ---------------------------------------------------------------------------
# dispatch_enqueue — specialist QueueTask drains via process_queue
# ---------------------------------------------------------------------------


class TestDispatchEnqueueSpecialistDrains:
    def test_specialist_task_drains(self, operator_layer: Path) -> None:
        from alc.queue import process_queue

        manifest = load_manifest(operator_layer)
        _write_specialist(operator_layer, "db")
        plan = ConductorPlan(
            items=[PlannedUnit(kind="specialist", name="db", task="document")]
        )

        files = dispatch_enqueue(plan, manifest, operator_layer, engine_override="mock")

        # The written task file must declare kind/name and drop the flow field.
        queue_dir = operator_layer.parent / manifest.queue_dir
        raw = yaml.safe_load((queue_dir / files[0]).read_text())
        assert raw["kind"] == "specialist"
        assert raw["name"] == "db"
        assert "flow" not in raw

        # Force isolate:false so no git repo is required, then drain.
        raw["isolate"] = False
        (queue_dir / files[0]).write_text(yaml.safe_dump(raw))

        results = process_queue(manifest, operator_layer)
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].flow == "db"


# ---------------------------------------------------------------------------
# conduct(parallel=...) — end-to-end over a real local git repo
# ---------------------------------------------------------------------------


def _init_git_repo(repo: Path) -> None:
    """Initialize a git repo with committed identity config inside *repo*."""
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


def _make_conduct_repo(base: Path) -> Path:
    """Build a committed git repo with a mixed catalog (ship flow + db specialist)."""
    repo = base / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    alc = repo / ".alc"
    (alc / "blueprints").mkdir(parents=True)
    (alc / "flows").mkdir(parents=True)
    (alc / "specialists").mkdir(parents=True)

    manifest = (
        "version: 1\n"
        "default_engine: mock\n"
        "compute_tiers:\n  standard:\n    mock: mock-small\n  deep:\n    mock: mock-large\n"
        "engines:\n  mock:\n    type: mock\n"
        "blueprints_dir: .alc/blueprints\n"
        "flows_dir: .alc/flows\n"
        "queue_dir: .alc/queue\n"
        "specialists_dir: .alc/specialists\n"
    )
    chore = (
        "---\nname: chore\npurpose: Apply a maintenance change.\ncompute_tier: standard\n"
        "checks:\n  - name: smoke\n    command: [\"true\"]\n---\n# Workflow\n1. Make it.\n"
    )
    plan_bp = (
        "---\nname: plan\npurpose: Plan a change.\ncompute_tier: deep\n"
        "checks:\n  - name: smoke\n    command: [\"true\"]\n---\n# Workflow\n1. Plan it.\n"
    )
    ship = (
        "name: ship\ndescription: Plan then build.\nstages:\n"
        "  - name: plan\n    blueprint: plan\n  - name: build\n    blueprint: chore\n"
    )
    specialist = (
        "name: db\narea: the database access layer\nblueprint: chore\n"
        "knowledge_path: .alc/specialists/db.knowledge.md\n"
    )
    (alc / "manifest.yaml").write_text(manifest)
    (alc / "blueprints" / "chore.md").write_text(chore)
    (alc / "blueprints" / "plan.md").write_text(plan_bp)
    (alc / "flows" / "ship.yaml").write_text(ship)
    (alc / "specialists" / "db.yaml").write_text(specialist)

    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "seed"], check=True, capture_output=True
    )
    return repo


class TestConductParallelMixedPlan:
    def test_parallel_dispatch_fills_units(self, tmp_path: Path, monkeypatch) -> None:
        repo = _make_conduct_repo(tmp_path)
        operator_layer = repo / ".alc"
        manifest = load_manifest(operator_layer)

        # Drive the planning turn to a mixed plan via a canned mock engine output.
        mixed = (
            '[{"kind":"flow","name":"ship","task":"build"},'
            '{"kind":"specialist","name":"db","task":"document"}]'
        )
        monkeypatch.setattr(
            "alc.engines.registry.resolve_engine",
            lambda name, engines: MockEngine(output=mixed),
        )

        report = conduct(
            manifest=manifest,
            operator_layer=operator_layer,
            goal="ship and document",
            engine_override="mock",
            parallel=True,
        )

        assert report.mode == "run"
        assert report.success is True
        assert len(report.units) == 2
        kinds = {u.kind for u in report.units}
        assert kinds == {"flow", "specialist"}
        assert all(u.success for u in report.units)


class TestConductParallelOutsideGitFallsBack:
    def test_serial_fallback_outside_git(self, operator_layer: Path, monkeypatch) -> None:
        _write_specialist(operator_layer, "db")
        manifest = load_manifest(operator_layer)

        mixed = (
            '[{"kind":"flow","name":"ship","task":"build"},'
            '{"kind":"specialist","name":"db","task":"document"}]'
        )
        monkeypatch.setattr(
            "alc.engines.registry.resolve_engine",
            lambda name, engines: MockEngine(output=mixed),
        )

        # operator_layer fixture lives in a plain tmp dir (no git) -> serial fallback.
        report = conduct(
            manifest=manifest,
            operator_layer=operator_layer,
            goal="ship and document",
            engine_override="mock",
            parallel=True,
        )

        assert report.mode == "run"
        # Serial dispatch: no fan-out units, one flow report for the ship flow.
        assert report.units == []
        assert len(report.flow_reports) == 1
        assert report.flow_reports[0].flow == "ship"
        assert report.success is True
