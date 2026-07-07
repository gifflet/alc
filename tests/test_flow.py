# test_flow.py — Tests for the Flow feature: FlowRunner, _compose_stage_directive, lint_flow.
# All tests are hermetic (no real model, no network); the end-to-end test uses the
# `operator_layer` fixture (a tmp Operator Layer), not a committed `.alc/`.
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from alc.flow import FlowRunner, _compose_stage_directive
from alc.intake import load_flow, load_manifest
from alc.models import Blueprint, Check, FlowDefinition, FlowStage, ReportSpec
from alc.policy import lint_flow


def _minimal_blueprint() -> Blueprint:
    """Return a minimal Blueprint sufficient for directive composition tests."""
    return Blueprint(
        name="plan",
        purpose="Produce a concise plan without writing code.",
        compute_tier="standard",
        checks=[Check(name="smoke", command=["true"])],
        report=ReportSpec(format="json", schema={}),
        workflow="## Plan Workflow\n\nRead the task, write the plan.",
    )


class TestComposeStageDirective:
    def test_threads_upstream_output_into_directive(self) -> None:
        blueprint = _minimal_blueprint()
        upstream = ["## plan output\nDO THE THING"]

        result = _compose_stage_directive(
            flow_name="ship",
            stage_name="build",
            blueprint=blueprint,
            task="tidy up the changelog",
            upstream_outputs=upstream,
        )

        # Upstream context must appear in the directive.
        assert "DO THE THING" in result
        assert "## Upstream context (previous stages)" in result
        # Blueprint workflow must appear too.
        assert blueprint.workflow in result

    def test_no_upstream_section_when_outputs_empty(self) -> None:
        blueprint = _minimal_blueprint()

        result = _compose_stage_directive(
            flow_name="ship",
            stage_name="plan",
            blueprint=blueprint,
            task="tidy up the changelog",
            upstream_outputs=[],
        )

        assert "## Upstream context" not in result
        assert blueprint.workflow in result

    def test_header_contains_flow_stage_task(self) -> None:
        blueprint = _minimal_blueprint()

        result = _compose_stage_directive(
            flow_name="my-flow",
            stage_name="my-stage",
            blueprint=blueprint,
            task="my task",
            upstream_outputs=[],
        )

        assert "my-flow" in result
        assert "my-stage" in result
        assert "my task" in result


class TestFlowRunnerEndToEnd:
    def test_flow_runs_all_stages_with_mock_engine(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)

        flows_dir = operator_layer.parent / manifest.flows_dir
        flow = load_flow(flows_dir, "ship")

        runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)
        report = runner.run(flow=flow, task="tidy up the changelog", engine_override="mock")

        assert report.success is True
        assert len(report.stages) == 2

        # Stage 0: plan blueprint
        assert report.stages[0].blueprint == "plan"
        assert report.stages[0].success is True

        # Stage 1: build stage references the chore blueprint
        assert report.stages[1].blueprint == "chore"
        assert report.stages[1].success is True

        # Aggregate scorecard: passes = sum of per-stage passes (each mock = 1).
        assert report.scorecard.passes == 2

        # FlowReport must be serialisable to JSON.
        raw = json.loads(report.model_dump_json())
        assert raw["success"] is True
        assert raw["flow"] == "ship"
        assert raw["engine"] == "mock"


class TestFlowSpecialistStage:
    """A Flow stage can run a Specialist via run_specialist in the shared workdir."""

    def _write_dev_specialist(self, operator_layer: Path) -> None:
        specialists_dir = operator_layer / "specialists"
        specialists_dir.mkdir(exist_ok=True)
        data = {
            "name": "dev",
            "area": "the implementation area",
            "blueprint": "chore",
            "knowledge_path": ".alc/specialists/dev.knowledge.md",
        }
        (specialists_dir / "dev.yaml").write_text(yaml.safe_dump(data))

    def test_specialist_stage_runs_and_threads_upstream(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        """Stage 0 runs the specialist (writes its Knowledge File); stage 1 sees
        stage 0's upstream output in its directive."""
        from alc.engine import Capabilities, EngineResult

        self._write_dev_specialist(operator_layer)

        # Flow: [ specialist:dev, blueprint:chore ] sharing one workdir.
        flow = FlowDefinition(
            name="demand",
            stages=[
                FlowStage(name="implement", specialist="dev"),
                FlowStage(name="validate", blueprint="chore"),
            ],
        )

        seen_directives: list[str] = []

        class _RecordingEngine:
            name = "mock"

            def capabilities(self) -> Capabilities:
                return Capabilities()

            def health_check(self) -> bool:
                return True

            def run(self, request):
                seen_directives.append(request.directive)
                return EngineResult(ok=True, output_text="STAGE-OUTPUT-MARKER")

        # Patch resolve_engine everywhere the flow path resolves it: runner.py binds
        # it at import time (the Act mandate); specialist.py imports it lazily from
        # the registry (the Learn turn), so patch the registry source too.
        monkeypatch.setattr(
            "alc.runner.resolve_engine", lambda name, engines: _RecordingEngine()
        )
        monkeypatch.setattr(
            "alc.engines.registry.resolve_engine",
            lambda name, engines: _RecordingEngine(),
        )

        manifest = load_manifest(operator_layer)
        runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)
        report = runner.run(flow=flow, task="ship the thing", engine_override="mock")

        assert report.success is True
        assert len(report.stages) == 2

        # Stage 0 came from the specialist path: its Knowledge File was written.
        knowledge_file = operator_layer / "specialists" / "dev.knowledge.md"
        assert knowledge_file.exists(), "specialist stage must run run_specialist (Learn wrote the Knowledge File)"

        # Stage 1's directive carries stage 0's upstream output.
        assert any("STAGE-OUTPUT-MARKER" in d for d in seen_directives)
        assert any("Upstream context (previous stages)" in d for d in seen_directives)


class TestLintFlow:
    def test_missing_blueprint_yields_error(self) -> None:
        flow = FlowDefinition(
            name="x",
            stages=[FlowStage(name="s", blueprint="does-not-exist")],
        )
        violations = lint_flow(flow, {"chore"})
        assert any(v.severity == "error" for v in violations)
        assert any(v.rule == "flow-blueprint-exists" for v in violations)

    def test_empty_stages_yields_error(self) -> None:
        flow = FlowDefinition(name="empty", stages=[])
        violations = lint_flow(flow, {"chore"})
        assert any(v.severity == "error" for v in violations)
        assert any(v.rule == "flow-has-stages" for v in violations)

    def test_valid_flow_yields_no_violations(self) -> None:
        flow = FlowDefinition(
            name="ship",
            stages=[
                FlowStage(name="plan", blueprint="plan"),
                FlowStage(name="build", blueprint="chore"),
            ],
        )
        violations = lint_flow(flow, {"plan", "chore"})
        assert violations == []

    def test_missing_specialist_yields_error(self) -> None:
        flow = FlowDefinition(
            name="x",
            stages=[FlowStage(name="s", specialist="ghost")],
        )
        violations = lint_flow(flow, set(), available_specialists=set())
        assert any(v.severity == "error" for v in violations)
        assert any(v.rule == "flow-specialist-exists" for v in violations)

    def test_present_specialist_yields_no_violations(self) -> None:
        flow = FlowDefinition(
            name="demand",
            stages=[FlowStage(name="implement", specialist="dev")],
        )
        violations = lint_flow(flow, set(), available_specialists={"dev"})
        assert violations == []


class TestFlowStageValidator:
    """FlowStage must reference exactly one of blueprint/specialist."""

    def test_both_blueprint_and_specialist_raises(self) -> None:
        with pytest.raises(ValidationError):
            FlowStage(name="s", blueprint="chore", specialist="dev")

    def test_neither_blueprint_nor_specialist_raises(self) -> None:
        with pytest.raises(ValidationError):
            FlowStage(name="s")

    def test_verify_only_with_specialist_raises(self) -> None:
        with pytest.raises(ValidationError):
            FlowStage(name="s", specialist="dev", verify_only=True)

    def test_blueprint_only_is_valid(self) -> None:
        stage = FlowStage(name="s", blueprint="chore")
        assert stage.blueprint == "chore"
        assert stage.specialist is None

    def test_specialist_only_is_valid(self) -> None:
        stage = FlowStage(name="s", specialist="dev")
        assert stage.specialist == "dev"
        assert stage.blueprint is None
