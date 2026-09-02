# test_conduct.py — Hermetic tests for the Conductor: parse_plan, plan_flows,
# dispatch_enqueue, dispatch_now. No real engine is ever called.
from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from alc.conduct import (
    build_catalog,
    conduct,
    derive_dependencies,
    dispatch_enqueue,
    dispatch_now,
    finalize_plan,
    parse_plan,
    plan_flows,
)
from alc.engines.mock import MockEngine
from alc.intake import load_manifest
from alc.models import ConductorPlan, PlannedFlow, PlannedUnit, QueueTask


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


class TestParsePlanDependencies:
    def test_reads_id_and_depends_on(self) -> None:
        raw = (
            '[{"id":"ingest","kind":"flow","name":"ship","task":"a"},'
            '{"kind":"flow","name":"ship","task":"b","depends_on":["ingest"]}]'
        )
        plan = parse_plan(raw, {"ship"})
        assert plan.items[0].id == "ingest"
        assert plan.items[0].depends_on == []
        assert plan.items[1].id is None
        assert plan.items[1].depends_on == ["ingest"]

    def test_absent_dependency_fields_default(self) -> None:
        plan = parse_plan('[{"kind":"flow","name":"ship","task":"x"}]', {"ship"})
        assert plan.items[0].id is None
        assert plan.items[0].depends_on == []

    def test_raises_for_unknown_dependency_id(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="unknown id"):
            parse_plan(
                '[{"kind":"flow","name":"ship","task":"x","depends_on":["nope"]}]',
                {"ship"},
            )

    def test_raises_when_depends_on_not_list_of_strings(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="depends_on"):
            parse_plan(
                '[{"id":"a","kind":"flow","name":"ship","task":"x","depends_on":[1]}]',
                {"ship"},
            )


class TestParsePlanTouches:
    def test_reads_touches(self) -> None:
        plan = parse_plan(
            '[{"kind":"flow","name":"ship","task":"a","touches":["src/app.js"]}]', {"ship"}
        )
        assert plan.items[0].touches == ["src/app.js"]

    def test_absent_touches_defaults_empty(self) -> None:
        plan = parse_plan('[{"kind":"flow","name":"ship","task":"a"}]', {"ship"})
        assert plan.items[0].touches == []

    def test_rejects_non_string_touches(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="touches"):
            parse_plan(
                '[{"kind":"flow","name":"ship","task":"a","touches":[1]}]', {"ship"}
            )


class TestParsePlanImpact:
    """Optional evidence-based `impact` field — ZERO
    runtime effect, same reporting-only contract as Blueprint.archetype."""

    def test_reads_impact_score_and_rationale(self) -> None:
        raw = (
            '[{"kind":"flow","name":"ship","task":"a",'
            '"impact":{"score":0.8,"rationale":"12 issue reports this week"}}]'
        )
        plan = parse_plan(raw, {"ship"})
        assert plan.items[0].impact is not None
        assert plan.items[0].impact.score == 0.8
        assert plan.items[0].impact.rationale == "12 issue reports this week"

    def test_absent_impact_defaults_none(self) -> None:
        plan = parse_plan('[{"kind":"flow","name":"ship","task":"a"}]', {"ship"})
        assert plan.items[0].impact is None

    def test_rejects_impact_missing_rationale(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="impact"):
            parse_plan(
                '[{"kind":"flow","name":"ship","task":"a","impact":{"score":1}}]',
                {"ship"},
            )

    def test_rejects_impact_with_non_numeric_score(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="impact"):
            parse_plan(
                '[{"kind":"flow","name":"ship","task":"a",'
                '"impact":{"score":"high","rationale":"x"}}]',
                {"ship"},
            )

    def test_rejects_impact_not_an_object(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="impact"):
            parse_plan(
                '[{"kind":"flow","name":"ship","task":"a","impact":"high"}]', {"ship"}
            )


class TestDeriveDependencies:
    """The CORE derives depends_on from `touches` overlap — the mechanical guarantee."""

    def _plan(self, *items: PlannedUnit) -> ConductorPlan:
        return ConductorPlan(items=list(items))

    def test_no_touches_plan_is_unchanged(self) -> None:
        # No touches anywhere -> byte-identical (no ids assigned, no deps derived).
        plan = self._plan(
            PlannedUnit(kind="flow", name="ship", task="a"),
            PlannedUnit(kind="flow", name="ship", task="b"),
        )
        out = derive_dependencies(plan)
        assert out.items[0].id is None and out.items[0].depends_on == []
        assert out.items[1].id is None and out.items[1].depends_on == []

    def test_overlapping_touches_serialize_the_later(self) -> None:
        out = derive_dependencies(
            self._plan(
                PlannedUnit(kind="flow", name="ship", task="a", touches=["src/app.js"]),
                PlannedUnit(
                    kind="flow", name="ship", task="b", touches=["src/app.js", "src/b.js"]
                ),
            )
        )
        assert out.items[0].id == "d0"
        assert out.items[1].depends_on == ["d0"]  # shares src/app.js

    def test_disjoint_touches_stay_independent(self) -> None:
        out = derive_dependencies(
            self._plan(
                PlannedUnit(kind="flow", name="ship", task="a", touches=["src/a.js"]),
                PlannedUnit(kind="flow", name="ship", task="b", touches=["src/b.js"]),
            )
        )
        assert out.items[1].depends_on == []

    def test_glob_overlap_is_detected(self) -> None:
        out = derive_dependencies(
            self._plan(
                PlannedUnit(kind="flow", name="ship", task="a", touches=["src/*.js"]),
                PlannedUnit(kind="flow", name="ship", task="b", touches=["src/app.js"]),
            )
        )
        assert out.items[1].depends_on == ["d0"]  # src/app.js matches src/*.js

    def test_no_touches_item_in_touches_aware_plan_is_serialized(self) -> None:
        out = derive_dependencies(
            self._plan(
                PlannedUnit(kind="flow", name="ship", task="a", touches=["src/a.js"]),
                PlannedUnit(kind="flow", name="ship", task="b"),  # no touches -> conservative
                PlannedUnit(kind="flow", name="ship", task="c", touches=["src/c.js"]),
            )
        )
        assert "d0" in out.items[1].depends_on  # b (no touches) waits for a
        assert "d1" in out.items[2].depends_on  # c waits for b (b overlaps everything)

    def test_explicit_depends_on_preserved_even_when_disjoint(self) -> None:
        out = derive_dependencies(
            self._plan(
                PlannedUnit(
                    kind="flow", name="ship", task="a", id="ingest", touches=["src/a.js"]
                ),
                PlannedUnit(
                    kind="flow", name="ship", task="b", touches=["src/b.js"],
                    depends_on=["ingest"],
                ),
            )
        )
        assert out.items[1].depends_on == ["ingest"]  # logical dep kept despite disjoint files

    def test_dispatch_enqueue_writes_derived_depends_on(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        plan = self._plan(
            PlannedUnit(kind="flow", name="ship", task="a", touches=["src/app.js"]),
            PlannedUnit(kind="flow", name="ship", task="b", touches=["src/app.js"]),
        )
        files = dispatch_enqueue(plan, manifest, operator_layer)
        queue_dir = operator_layer.parent / manifest.queue_dir
        tasks = [
            QueueTask.model_validate(yaml.safe_load((queue_dir / f).read_text()))
            for f in files
        ]
        assert tasks[0].id == "d0"
        assert tasks[1].depends_on == ["d0"]  # the core serialized the overlapping pair


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
# build_catalog — equivalence with conduct()'s former inline logic
# ---------------------------------------------------------------------------


class TestBuildCatalog:
    def test_returns_catalog_text_and_name_sets(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        catalog_text, flows, specialists = build_catalog(manifest, operator_layer)

        # The demo operator_layer ships a single 'ship' flow, no specialists.
        assert flows == {"ship"}
        assert specialists == set()
        assert catalog_text == (
            "- ship (flow): Plan a change, then implement it — each stage its "
            "own mandate. (stages: plan, chore)"
        )

    def test_equivalence_with_former_inline_logic(self, operator_layer: Path) -> None:
        # Reproduce the exact inline logic conduct() used before build_catalog and
        # assert the helper returns the same tuple.
        from alc.intake import load_all_flows, load_all_specialists

        manifest = load_manifest(operator_layer)
        flows = load_all_flows(manifest, operator_layer)
        specialists = load_all_specialists(manifest, operator_layer)
        lines = [
            f"- {f.name} (flow): {f.description} "
            f"(stages: {', '.join(s.blueprint for s in f.stages)})"
            for f in flows
        ]
        lines += [f"- {s.name} (specialist): {s.area}" for s in specialists]
        expected_text = "\n".join(lines) if lines else "(no targets available)"
        expected = (
            expected_text,
            {f.name for f in flows},
            {s.name for s in specialists},
        )
        assert build_catalog(manifest, operator_layer) == expected

    def test_specialist_stage_renders_without_crash(self, operator_layer: Path) -> None:
        # Regression: a flow with a specialist stage (blueprint=None) must not crash
        # the catalog builder (dogfood: the linkedin-vagas `demand` flow is dev + qa).
        import yaml

        (operator_layer / "flows" / "demand.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": "demand",
                    "description": "implement then validate",
                    "stages": [
                        {"name": "impl", "specialist": "dev"},
                        {"name": "check", "blueprint": "chore"},
                    ],
                }
            )
        )
        manifest = load_manifest(operator_layer)
        catalog_text, flows, _ = build_catalog(manifest, operator_layer)

        assert "demand" in flows
        # The specialist stage renders by its specialist name; the blueprint stage by its blueprint.
        assert "(stages: dev, chore)" in catalog_text


# ---------------------------------------------------------------------------
# finalize_plan — parse + cheap corrective retry
# ---------------------------------------------------------------------------


class TestFinalizePlan:
    def test_valid_first_output_no_extra_turn(self) -> None:
        # A parseable first output returns immediately, never touching the engine.
        class _NeverCalled:
            name = "mock"

            def capabilities(self):
                from alc.engine import Capabilities

                return Capabilities()

            def health_check(self) -> bool:
                return True

            def run(self, request):  # pragma: no cover - must not run
                raise AssertionError("engine.run must not be called on valid output")

        plan = finalize_plan(
            engine=_NeverCalled(),  # type: ignore[arg-type]
            model=None,
            first_output='[{"kind":"flow","name":"ship","task":"x"}]',
            available_flows={"ship"},
            available_specialists=set(),
        )
        assert len(plan.items) == 1
        assert plan.items[0].name == "ship"

    def test_invalid_then_valid_self_heals(self) -> None:
        # First output is bad; one corrective engine turn returns valid JSON.
        call_count = 0

        class _CorrectiveEngine:
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
                return EngineResult(
                    ok=True, output_text='[{"kind":"flow","name":"ship","task":"x"}]'
                )

        plan = finalize_plan(
            engine=_CorrectiveEngine(),  # type: ignore[arg-type]
            model=None,
            first_output="not json at all",
            available_flows={"ship"},
            available_specialists=set(),
        )
        assert call_count == 1  # exactly one corrective turn healed it
        assert plan.items[0].name == "ship"

    def test_invalid_through_all_retries_raises(self) -> None:
        import pytest

        engine = MockEngine(output="still not json")
        with pytest.raises(ValueError, match="could not be parsed"):
            finalize_plan(
                engine=engine,
                model=None,
                first_output="bad start",
                available_flows={"ship"},
                available_specialists=set(),
                max_retries=2,
            )

    def test_engine_failure_stops_retrying(self) -> None:
        # A corrective turn whose engine returns ok=False (API error / quota) must
        # stop immediately, not hammer the dead engine for every retry.
        import pytest

        call_count = 0

        class _FailingEngine:
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
                return EngineResult(ok=False, output_text="[gemini] 429 quota exceeded")

        with pytest.raises(ValueError, match="engine failed"):
            finalize_plan(
                engine=_FailingEngine(),  # type: ignore[arg-type]
                model=None,
                first_output="not json",
                available_flows={"ship"},
                available_specialists=set(),
                max_retries=3,
            )
        assert call_count == 1  # stopped after the first failed corrective, not 3


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

    def test_default_isolate_is_true(self, operator_layer: Path) -> None:
        # The Conductor path (no isolate arg) stays byte-identical: isolate True.
        manifest = load_manifest(operator_layer)
        plan = ConductorPlan(items=[PlannedUnit(kind="flow", name="ship", task="x")])

        files = dispatch_enqueue(plan, manifest, operator_layer)

        queue_dir = operator_layer.parent / manifest.queue_dir
        raw = yaml.safe_load((queue_dir / files[0]).read_text())
        assert QueueTask.model_validate(raw).isolate is True

    def test_isolate_false_written_to_each_file(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        plan = ConductorPlan(items=[
            PlannedUnit(kind="flow", name="ship", task="alpha"),
            PlannedUnit(kind="flow", name="ship", task="beta"),
        ])

        files = dispatch_enqueue(plan, manifest, operator_layer, isolate=False)

        queue_dir = operator_layer.parent / manifest.queue_dir
        for filename in files:
            raw = yaml.safe_load((queue_dir / filename).read_text())
            assert QueueTask.model_validate(raw).isolate is False

    def test_filenames_sort_in_plan_order(self, operator_layer: Path) -> None:
        # Drain order (process_queue sorts *.yaml by name) must follow plan order,
        # so the written filenames must sort item 0 before item 1 before item 2.
        manifest = load_manifest(operator_layer)
        plan = ConductorPlan(items=[
            PlannedUnit(kind="flow", name="ship", task="first"),
            PlannedUnit(kind="flow", name="ship", task="second"),
            PlannedUnit(kind="flow", name="ship", task="third"),
        ])

        files = dispatch_enqueue(plan, manifest, operator_layer)

        queue_dir = operator_layer.parent / manifest.queue_dir
        sorted_names = sorted(f.name for f in queue_dir.glob("*.yaml"))
        # dispatch_enqueue must RETURN the filenames already in plan (= sorted) order.
        assert files == sorted_names
        tasks = [
            yaml.safe_load((queue_dir / name).read_text())["task"]
            for name in sorted_names
        ]
        assert tasks == ["first", "second", "third"]

    def test_filename_carries_title_slug(self, operator_layer: Path) -> None:
        # The filename embeds a slug of the task's first line, so the queue
        # header (▶ <file> — …) and archived report are human-readable.
        manifest = load_manifest(operator_layer)
        plan = ConductorPlan(items=[
            PlannedUnit(
                kind="flow",
                name="ship",
                task="Add sort control to the dashboard\n\ndetails here",
            ),
        ])

        files = dispatch_enqueue(plan, manifest, operator_layer)

        assert "add-sort-control-to-the-dashboard" in files[0]
        # Only the first line becomes the slug — the body is never in the name.
        assert "details" not in files[0]

    def test_prefix_is_configurable(self, operator_layer: Path) -> None:
        # The kind:plan replenish passes prefix="plan"; the default is "conduct".
        manifest = load_manifest(operator_layer)
        plan = ConductorPlan(items=[
            PlannedUnit(kind="flow", name="ship", task="alpha task"),
            PlannedUnit(kind="flow", name="ship", task="beta task"),
        ])

        planned = dispatch_enqueue(plan, manifest, operator_layer, prefix="plan")
        assert all(f.startswith("plan-") for f in planned)

    def test_untitled_task_falls_back_to_uid(self, operator_layer: Path) -> None:
        # A task whose first line has no usable characters still gets a valid,
        # unique filename (prefix-index-uid), never an empty slug segment.
        manifest = load_manifest(operator_layer)
        plan = ConductorPlan(items=[PlannedUnit(kind="flow", name="ship", task="!!! ???")])

        files = dispatch_enqueue(plan, manifest, operator_layer)

        assert files[0].startswith("conduct-000-")
        assert "--" not in files[0]  # no empty slug segment

    def test_round_trips_id_and_depends_on(self, operator_layer: Path) -> None:
        # id + depends_on written into the task file survive a QueueTask reparse.
        manifest = load_manifest(operator_layer)
        plan = ConductorPlan(items=[
            PlannedUnit(kind="flow", name="ship", task="a", id="ingest"),
            PlannedUnit(kind="flow", name="ship", task="b", depends_on=["ingest"]),
        ])

        files = dispatch_enqueue(plan, manifest, operator_layer)

        queue_dir = operator_layer.parent / manifest.queue_dir
        first = QueueTask.model_validate(
            yaml.safe_load((queue_dir / files[0]).read_text())
        )
        second = QueueTask.model_validate(
            yaml.safe_load((queue_dir / files[1]).read_text())
        )
        assert first.id == "ingest"
        assert first.depends_on == []
        assert second.depends_on == ["ingest"]

    def test_omits_dependency_fields_when_absent(self, operator_layer: Path) -> None:
        # A plan with no id/depends_on writes legacy-clean files (keys omitted).
        manifest = load_manifest(operator_layer)
        plan = ConductorPlan(items=[PlannedUnit(kind="flow", name="ship", task="x")])

        files = dispatch_enqueue(plan, manifest, operator_layer)

        queue_dir = operator_layer.parent / manifest.queue_dir
        raw = yaml.safe_load((queue_dir / files[0]).read_text())
        assert "id" not in raw
        assert "depends_on" not in raw


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
# PlannedUnit / PlannedFlow constructor compatibility
# ---------------------------------------------------------------------------


class TestPlannedUnitConstructorCompat:
    def test_planned_unit_canonical_shape(self) -> None:
        """PlannedUnit(kind=..., name=..., task=...) constructs without error."""
        unit = PlannedUnit(kind="flow", name="ship", task="do it")
        assert unit.kind == "flow"
        assert unit.name == "ship"
        assert unit.task == "do it"

    def test_planned_flow_alias_legacy_shape(self) -> None:
        """PlannedFlow(flow=..., task=...) constructs and maps kind/name correctly."""
        item = PlannedFlow(flow="ship", task="build the widget")  # type: ignore[call-arg]
        assert item.kind == "flow"
        assert item.name == "ship"
        assert item.task == "build the widget"

    def test_planned_flow_flow_property_round_trips(self) -> None:
        """The back-compat .flow property returns the unit name."""
        item = PlannedFlow(flow="deploy", task="push it")  # type: ignore[call-arg]
        assert item.flow == "deploy"

    def test_conductor_plan_model_validate_legacy_dict(self) -> None:
        """ConductorPlan.model_validate works with legacy {flow, task} dicts in items."""
        plan = ConductorPlan.model_validate({
            "items": [{"flow": "ship", "task": "legacy task"}]
        })
        assert len(plan.items) == 1
        assert plan.items[0].kind == "flow"
        assert plan.items[0].name == "ship"
        assert plan.items[0].task == "legacy task"

    def test_conductor_plan_model_validate_current_dict(self) -> None:
        """ConductorPlan.model_validate works with the current {kind, name, task} shape."""
        plan = ConductorPlan.model_validate({
            "items": [{"kind": "specialist", "name": "db", "task": "document"}]
        })
        assert plan.items[0].kind == "specialist"
        assert plan.items[0].name == "db"

    def test_impact_defaults_none_and_accepts_a_valid_object(self) -> None:
        from alc.models import Impact

        bare = PlannedUnit(kind="flow", name="ship", task="x")
        assert bare.impact is None

        scored = PlannedUnit(
            kind="flow",
            name="ship",
            task="x",
            impact=Impact(score=0.5, rationale="some evidence"),
        )
        assert scored.impact == Impact(score=0.5, rationale="some evidence")


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

        # The specialist's Act outcome is wrapped into a FlowReport so it counts
        # toward the overall success.
        assert len(reports) == 1
        assert reports[0].flow == "db"
        assert reports[0].success is True

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


class TestDispatchNowSurfacesSpecialistFailure:
    def test_failing_specialist_makes_serial_conduct_unsuccessful(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        # A blueprint whose only check always fails, so the specialist's Act fails.
        failing_bp = (
            "---\nname: failing\npurpose: Always fails its check.\ncompute_tier: standard\n"
            'checks:\n  - name: nope\n    command: ["false"]\n---\n# Workflow\n1. Do nothing.\n'
        )
        (operator_layer / "blueprints" / "failing.md").write_text(failing_bp)

        specialists_dir = operator_layer / "specialists"
        specialists_dir.mkdir(exist_ok=True)
        (specialists_dir / "db.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": "db",
                    "area": "the database access layer",
                    "blueprint": "failing",
                    "knowledge_path": ".alc/specialists/db.knowledge.md",
                }
            )
        )

        manifest = load_manifest(operator_layer)

        # Drive the planning turn to a specialist-only plan.
        monkeypatch.setattr(
            "alc.engines.registry.resolve_engine",
            lambda name, engines: MockEngine(
                output='[{"kind":"specialist","name":"db","task":"document"}]'
            ),
        )

        report = conduct(
            manifest=manifest,
            operator_layer=operator_layer,
            goal="document the db",
            engine_override="mock",
        )

        # Serial dispatch must surface the failing specialist, not report success.
        assert report.mode == "run"
        assert len(report.flow_reports) == 1
        assert report.flow_reports[0].flow == "db"
        assert report.flow_reports[0].success is False
        assert report.success is False


class TestConductParallelHonorsEngineOverride:
    def test_units_run_on_override_not_manifest_default(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from alc.engine import Capabilities, EngineResult

        class _NamedMockEngine:
            """Mock engine that reports a distinct name (records which engine ran)."""

            def __init__(self, name: str, output: str | None = None) -> None:
                self.name = name
                self._output = output

            def capabilities(self) -> Capabilities:
                return Capabilities()

            def health_check(self) -> bool:
                return True

            def run(self, request):
                text = self._output if self._output is not None else "[mock] applied"
                return EngineResult(ok=True, output_text=text)

        # Repo whose manifest default engine ("base") differs from the override
        # ("chosen"); both are mock-typed so the run is hermetic.
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        alc = repo / ".alc"
        (alc / "blueprints").mkdir(parents=True)
        (alc / "flows").mkdir(parents=True)
        manifest_yaml = (
            "version: 1\n"
            "default_engine: base\n"
            "compute_tiers:\n  standard:\n    base: base-small\n    chosen: chosen-small\n"
            "engines:\n  base:\n    type: mock\n  chosen:\n    type: mock\n"
            "blueprints_dir: .alc/blueprints\n"
            "flows_dir: .alc/flows\n"
            "queue_dir: .alc/queue\n"
        )
        chore = (
            "---\nname: chore\npurpose: Apply a change.\ncompute_tier: standard\n"
            'checks:\n  - name: smoke\n    command: ["true"]\n---\n# Workflow\n1. Make it.\n'
        )
        ship = (
            "name: ship\ndescription: Build it.\nstages:\n"
            "  - name: build\n    blueprint: chore\n"
        )
        (alc / "manifest.yaml").write_text(manifest_yaml)
        (alc / "blueprints" / "chore.md").write_text(chore)
        (alc / "flows" / "ship.yaml").write_text(ship)
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "seed"], check=True, capture_output=True
        )

        operator_layer = alc
        manifest = load_manifest(operator_layer)

        plan_output = '[{"kind":"flow","name":"ship","task":"build"}]'

        def _resolve(name: str, engines: dict):
            # Return a named engine so RunReport.engine records which one ran.
            return _NamedMockEngine(name, output=plan_output)

        # conduct() resolves the planning engine via the registry namespace, while
        # execute_mandate resolves the dispatch engine via runner's own import.
        monkeypatch.setattr("alc.engines.registry.resolve_engine", _resolve)
        monkeypatch.setattr("alc.runner.resolve_engine", _resolve)

        report = conduct(
            manifest=manifest,
            operator_layer=operator_layer,
            goal="build it",
            engine_override="chosen",
            parallel=True,
        )

        assert report.success is True
        assert len(report.units) == 1
        # The dispatched unit must have run on the override, not the manifest default.
        stages = report.units[0].flow_report.stages
        assert all(s.engine == "chosen" for s in stages)


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
        # Serial dispatch: no fan-out units; one report per plan item — the ship
        # flow plus the db specialist's Act wrapped as a FlowReport.
        assert report.units == []
        assert len(report.flow_reports) == 2
        assert [r.flow for r in report.flow_reports] == ["ship", "db"]
        assert report.success is True
