# flow.py — FlowRunner: orchestrates a deterministic multi-stage pipeline.
# A Flow composes multiple Single-Mandate invocations, threading each stage's
# output into the next as upstream context. The control plane (Policy Gate,
# Assurance Loop, Scorecard) is reused for every stage via execute_mandate.
from __future__ import annotations

from pathlib import Path

from alc.intake import load_blueprint
from alc.models import (
    Blueprint,
    FlowDefinition,
    FlowReport,
    Manifest,
    RunReport,
    Scorecard,
)
from alc.policy import has_errors, lint, lint_flow
from alc.runner import PolicyViolationError, execute_mandate
from alc.verifier import Verifier


def _compose_stage_directive(
    flow_name: str,
    stage_name: str,
    blueprint: Blueprint,
    task: str,
    upstream_outputs: list[str],
    extra_context: str | None = None,
) -> str:
    """Compose the Single-Mandate directive for one Flow stage.

    Includes a flow/stage/task header, optional primed context (Context Budget
    Trim move), optional upstream context from previous stages, and the Blueprint
    workflow body.

    This is a pure module-level function so it can be unit-tested in isolation.

    Args:
        flow_name: Name of the enclosing Flow (for the header).
        stage_name: Name of this stage (for the header).
        blueprint: The stage Blueprint (provides name, purpose, workflow).
        task: The original task string passed to the Flow.
        upstream_outputs: Labeled output blocks from all preceding stages.
            Each entry is already formatted as "## <stage> output\\n<text>".
        extra_context: Optional primed context string (Primer text, bundle summary,
            or both joined). Injected after the header and before the upstream
            section when truthy. Default None leaves behavior unchanged.

    Returns:
        The fully composed directive string.
    """
    header = (
        f"# ALC Flow: {flow_name}\n"
        f"Stage:     {stage_name}\n"
        f"Blueprint: {blueprint.name}\n"
        f"Purpose:   {blueprint.purpose}\n"
        f"Task:      {task}\n"
        "\n---\n"
    )

    primed_section = ""
    if extra_context:
        primed_section = "## Primed context\n\n" + extra_context + "\n\n---\n"

    upstream_section = ""
    if upstream_outputs:
        upstream_section = (
            "\n## Upstream context (previous stages)\n\n"
            + "\n\n".join(upstream_outputs)
            + "\n\n---\n"
        )

    return header + primed_section + upstream_section + blueprint.workflow


class FlowRunner:
    """Orchestrates a Flow: runs each stage in order as a separate Single Mandate.

    The Policy Gate is enforced before any stage runs. Stages are executed
    sequentially; a stage failure immediately aborts the pipeline (fail-fast).

    NOTE: Per-stage worktree isolation is deferred to the Detached maturity stage.
    All stages share Path.cwd() for the MVP.
    """

    def __init__(self, manifest: Manifest, operator_layer: Path) -> None:
        self._manifest = manifest
        self._operator_layer = operator_layer

    def run(
        self,
        flow: FlowDefinition,
        task: str,
        engine_override: str | None = None,
        workdir: Path | None = None,
        extra_context: str | None = None,
    ) -> FlowReport:
        """Execute every stage in the Flow and return an aggregate FlowReport.

        Args:
            flow: The FlowDefinition declaring the ordered pipeline of stages.
            task: The free-text task description provided by the operator.
            engine_override: If set, use this engine name instead of manifest.default_engine.
            workdir: Shared directory for all stages. Defaults to Path.cwd() when None.
                     Pass an IsolatedWorktree path so every stage shares one worktree
                     (preserving the plan→build file hand-off).
            extra_context: Optional primed context string (Primer text, bundle summary,
                or both joined). Passed to every stage's directive unchanged (Context
                Budget Trim move). Default None leaves behavior unchanged.

        Returns:
            FlowReport with per-stage RunReports and an aggregate Scorecard.

        Raises:
            PolicyViolationError: If the Flow Policy Gate finds error-level violations.
        """
        blueprints_dir = self._operator_layer.parent / self._manifest.blueprints_dir

        # Load every stage Blueprint upfront for the Policy Gate.
        stage_blueprints: dict[str, Blueprint] = {}
        for stage in flow.stages:
            bp = load_blueprint(blueprints_dir, stage.blueprint)
            # Apply optional per-stage compute_tier override.
            if stage.compute_tier is not None:
                bp = bp.model_copy(update={"compute_tier": stage.compute_tier})
            stage_blueprints[stage.name] = bp

        # Flow Policy Gate: lint blueprints + lint the flow itself.
        all_blueprints = list(stage_blueprints.values())
        violations = lint(self._manifest, all_blueprints)
        available_names = {stage.blueprint for stage in flow.stages}
        violations += lint_flow(flow, available_names)

        if has_errors(violations):
            error_msgs = [v.message for v in violations if v.severity == "error"]
            raise PolicyViolationError(
                "Flow Policy Gate blocked this run:\n"
                + "\n".join(f"  - {m}" for m in error_msgs)
            )

        # Resolve engine name for the report header.
        engine_name = engine_override or self._manifest.default_engine

        stage_reports: list[RunReport] = []
        upstream_outputs: list[str] = []

        for stage in flow.stages:
            blueprint = stage_blueprints[stage.name]

            if stage.verify_only:
                # Verify-only stage: run checks as a pure gate — no engine turn.
                wd = workdir or Path.cwd()
                check_results = Verifier().run(blueprint.checks, wd)
                all_passed = all(cr.passed for cr in check_results)
                summary_lines = [
                    f"{cr.name}: {'pass' if cr.passed else 'fail'}"
                    for cr in check_results
                ]
                report = RunReport(
                    blueprint=blueprint.name,
                    engine="(verify-only)",
                    success=all_passed,
                    attempts=[],
                    scorecard=Scorecard(
                        span=sum(1 for cr in check_results if cr.passed),
                        passes=0,
                        streak=0,
                        touch=0,
                    ),
                    output_text="\n".join(summary_lines),
                )
            else:
                directive = _compose_stage_directive(
                    flow_name=flow.name,
                    stage_name=stage.name,
                    blueprint=blueprint,
                    task=task,
                    upstream_outputs=upstream_outputs,
                    extra_context=extra_context,
                )

                report = execute_mandate(
                    manifest=self._manifest,
                    blueprint=blueprint,
                    directive=directive,
                    engine_override=engine_override,
                    workdir=workdir,
                )

            stage_reports.append(report)

            # Fail-fast: stop the pipeline if this stage did not succeed.
            if not report.success:
                break

            # Thread this stage's output into the next stage's context.
            upstream_outputs.append(f"## {stage.name} output\n{report.output_text}")

        # Aggregate Scorecard across all executed stages.
        success = len(stage_reports) == len(flow.stages) and all(
            r.success for r in stage_reports
        )
        aggregate_scorecard = Scorecard(
            span=sum(r.scorecard.span for r in stage_reports),
            passes=sum(r.scorecard.passes for r in stage_reports),
            streak=1 if success and all(r.scorecard.streak == 1 for r in stage_reports) else 0,
            touch=0,
        )

        return FlowReport(
            flow=flow.name,
            engine=engine_name,
            success=success,
            stages=stage_reports,
            scorecard=aggregate_scorecard,
        )
