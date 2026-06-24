# test_flow.py — Tests for the Flow feature: FlowRunner, _compose_stage_directive, lint_flow.
# All tests are hermetic (no real model, no network); the end-to-end test uses the
# `operator_layer` fixture (a tmp Operator Layer), not a committed `.alc/`.
from __future__ import annotations

import json
from pathlib import Path

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
