# test_conduct.py — Hermetic tests for the Conductor: parse_plan, plan_flows,
# dispatch_enqueue, dispatch_now. No real engine is ever called.
from __future__ import annotations

from pathlib import Path

import yaml

from alc.conduct import dispatch_enqueue, dispatch_now, parse_plan, plan_flows
from alc.engines.mock import MockEngine
from alc.intake import load_manifest
from alc.models import ConductorPlan, PlannedFlow, QueueTask


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
            PlannedFlow(flow="ship", task="first"),
            PlannedFlow(flow="ship", task="second"),
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
            PlannedFlow(flow="ship", task="alpha"),
            PlannedFlow(flow="ship", task="beta"),
        ])

        files = dispatch_enqueue(plan, manifest, operator_layer)

        queue_dir = operator_layer.parent / manifest.queue_dir
        for filename, item in zip(files, plan.items):
            raw = yaml.safe_load((queue_dir / filename).read_text())
            # Must parse as a valid QueueTask.
            qt = QueueTask.model_validate(raw)
            assert qt.isolate is True
            assert qt.flow == item.flow
            assert qt.task == item.task

    def test_engine_override_written_when_set(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        plan = ConductorPlan(items=[PlannedFlow(flow="ship", task="x")])

        files = dispatch_enqueue(plan, manifest, operator_layer, engine_override="mock")

        queue_dir = operator_layer.parent / manifest.queue_dir
        raw = yaml.safe_load((queue_dir / files[0]).read_text())
        assert raw["engine"] == "mock"

    def test_no_engine_field_when_override_is_none(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        plan = ConductorPlan(items=[PlannedFlow(flow="ship", task="x")])

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
        plan = ConductorPlan(items=[PlannedFlow(flow="ship", task="tidy")])

        reports = dispatch_now(plan, manifest, operator_layer, engine_override="mock")

        assert len(reports) == 1
        report = reports[0]
        assert isinstance(report, FlowReport)
        assert report.success is True
        assert report.flow == "ship"
