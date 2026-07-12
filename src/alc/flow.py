# flow.py — FlowRunner: orchestrates a deterministic multi-stage pipeline.
# A Flow composes multiple Single-Mandate invocations, threading each stage's
# output into the next as upstream context. The control plane (Policy Gate,
# Assurance Loop, Scorecard) is reused for every stage via execute_mandate.
from __future__ import annotations

import sys
from pathlib import Path

from alc.commit import commit_workdir, has_non_alc_changes, revert_workdir
from alc.events import emit
from alc.intake import load_blueprint, load_specialist, resolve_checks
from alc.models import (
    Blueprint,
    FlowDefinition,
    FlowReport,
    FlowStage,
    Manifest,
    RunReport,
    Scorecard,
    Specialist,
)
from alc.policy import has_errors, lint, lint_flow
from alc.prompts import expand_includes
from alc.runner import PolicyViolationError, execute_mandate
from alc.specialist import run_specialist
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


def _stage_blueprint(
    blueprint: Blueprint,
    stage: FlowStage,
    tier_override: str | None,
) -> Blueprint:
    """Return the effective Blueprint for a Flow stage, applying Compute Tier priority.

    Priority (highest first):
        1. tier_override  — per-invocation override supplied via ``--tier``
        2. stage.compute_tier — per-stage override declared in the Flow YAML
        3. blueprint's own compute_tier — the Blueprint default

    A new Blueprint is returned via model_copy only when the tier actually
    changes; otherwise the original object is returned unchanged.

    Args:
        blueprint: The base Blueprint loaded from the Operator Layer.
        stage: The FlowStage describing this pipeline step.
        tier_override: Optional per-invocation Compute Tier name (from CLI ``--tier``).

    Returns:
        Blueprint with the effective compute_tier applied.
    """
    effective_tier: str | None = tier_override or stage.compute_tier
    if effective_tier is not None and effective_tier != blueprint.compute_tier:
        return blueprint.model_copy(update={"compute_tier": effective_tier})
    return blueprint


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
        tier_override: str | None = None,
        env: dict[str, str] | None = None,
        skip_commit: bool = False,
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
            tier_override: If set, override the Compute Tier for every stage in this
                invocation (takes precedence over stage.compute_tier and Blueprint default).
            env: Extra environment variables injected into every stage's engine turn
                (e.g. the worktree's ALC_PORT range). Threaded to each stage's
                execute_mandate / run_specialist call. None -> unchanged (byte-identical).
            skip_commit: When True, SKIP both the terminal commit AND the
                revert-on-failure — the enclosing IsolatedWorktree owns the commit
                (on success) and the discard (on failure), so the FlowRunner must
                not double-commit/revert. ``commit_sha`` stays None. Default False
                leaves behavior byte-identical.

        Returns:
            FlowReport with per-stage RunReports and an aggregate Scorecard.

        Raises:
            PolicyViolationError: If the Flow Policy Gate finds error-level violations.
        """
        blueprints_dir = self._operator_layer.parent / self._manifest.blueprints_dir
        specialists_dir = self._operator_layer.parent / self._manifest.specialists_dir

        # Load every stage's effective Blueprint upfront for the Policy Gate. A
        # blueprint stage names its Blueprint directly; a specialist stage resolves
        # its Blueprint through the Specialist (whose Act step it will run).
        stage_blueprints: dict[str, Blueprint] = {}
        stage_specialists: dict[str, Specialist] = {}
        for stage in flow.stages:
            if stage.specialist is not None:
                specialist = load_specialist(specialists_dir, stage.specialist)
                stage_specialists[stage.name] = specialist
                bp = load_blueprint(blueprints_dir, specialist.blueprint)
            else:
                bp = load_blueprint(blueprints_dir, stage.blueprint)
            # Apply Compute Tier priority: tier_override > stage.compute_tier > blueprint default.
            bp = _stage_blueprint(bp, stage, tier_override)
            stage_blueprints[stage.name] = bp

        # Flow Policy Gate: lint blueprints + lint the flow itself.
        all_blueprints = list(stage_blueprints.values())
        violations = lint(self._manifest, all_blueprints)
        available_blueprints = {
            stage.blueprint for stage in flow.stages if stage.blueprint is not None
        }
        available_specialists = {
            stage.specialist for stage in flow.stages if stage.specialist is not None
        }
        violations += lint_flow(flow, available_blueprints, available_specialists)

        if has_errors(violations):
            error_msgs = [v.message for v in violations if v.severity == "error"]
            raise PolicyViolationError(
                "Flow Policy Gate blocked this run:\n"
                + "\n".join(f"  - {m}" for m in error_msgs)
            )

        # Resolve engine name for the report header.
        engine_name = engine_override or self._manifest.default_engine

        effective_workdir = workdir or Path.cwd()

        # Observe: announce the flow (best-effort; no-op when no run log is bound).
        emit(
            "flow_started",
            flow=flow.name,
            task=task,
            stages=[s.name for s in flow.stages],
        )

        # Clean-tree guard: a committing Flow in a shared (non-isolated) workdir must
        # not sweep pre-existing, unrelated work into its terminal commit. If the
        # workdir has uncommitted non-.alc/ changes, abort before running any stage.
        # (In an isolated worktree the tree is fresh from HEAD, so this passes.)
        if (
            flow.commit is not None
            and flow.commit.enabled
            and has_non_alc_changes(effective_workdir)
        ):
            print(
                "▶ flow aborted — the workdir has uncommitted non-.alc/ changes; a "
                "committing flow requires a clean tree.",
                file=sys.stderr,
                flush=True,
            )
            emit("flow_finished", success=False)
            return FlowReport(
                flow=flow.name,
                engine=engine_name,
                success=False,
                stages=[],
                scorecard=Scorecard(span=0, passes=0, streak=0, touch=0),
            )

        stage_reports: list[RunReport] = []
        upstream_outputs: list[str] = []

        for stage in flow.stages:
            blueprint = stage_blueprints[stage.name]

            # Announce the active stage before any engine or verifier work.
            if stage.specialist is not None:
                _stage_header = f"▶ stage {stage.name} — specialist:{stage.specialist}"
                emit("stage_started", stage=stage.name, specialist=stage.specialist)
            else:
                _stage_header = f"▶ stage {stage.name} — blueprint:{blueprint.name}"
                emit("stage_started", stage=stage.name, blueprint=blueprint.name)
            if stage.verify_only:
                _stage_header += " (verify-only)"
            print(_stage_header, file=sys.stderr, flush=True)

            if stage.verify_only:
                # Verify-only stage: run checks as a pure gate — no engine turn.
                wd = workdir or Path.cwd()
                check_results = Verifier(
                    max_output_chars=self._manifest.check_output_chars
                ).run(resolve_checks(self._manifest, blueprint), wd)
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
                        # A passing gate is one-shot by definition (zero repairs);
                        # a failing gate is not a successful one-shot run.
                        streak=1 if all_passed else 0,
                        touch=0,
                    ),
                    output_text="\n".join(summary_lines),
                )
            elif stage.specialist is not None:
                # Specialist stage: run its Recall -> Act -> Learn cycle in the
                # flow's shared workdir (so it sees prior stages' edits and keeps
                # its Knowledge File). The Act RunReport is this stage's report.
                # Merge flow-level extra_context (primer/bundle) with upstream
                # stage outputs so the specialist receives both, mirroring what
                # blueprint stages get via _compose_stage_directive.
                specialist = stage_specialists[stage.name]
                _specialist_ctx_parts = [p for p in [extra_context, "\n\n".join(upstream_outputs)] if p]
                _specialist_ctx = "\n\n".join(_specialist_ctx_parts) or None
                specialist_report = run_specialist(
                    manifest=self._manifest,
                    operator_layer=self._operator_layer,
                    specialist=specialist,
                    task=task,
                    engine_override=engine_override,
                    workdir=workdir,
                    extra_context=_specialist_ctx,
                    env=env,
                )
                report = specialist_report.act
            else:
                directive = _compose_stage_directive(
                    flow_name=flow.name,
                    stage_name=stage.name,
                    blueprint=blueprint,
                    task=task,
                    upstream_outputs=upstream_outputs,
                    extra_context=extra_context,
                )
                # Expand any {{prompt:<name>}} includes (compose stays pure; the
                # expansion happens here where we have the operator_layer). A
                # workflow with no include token is returned unchanged.
                directive = expand_includes(
                    directive, self._operator_layer, self._manifest
                )

                report = execute_mandate(
                    manifest=self._manifest,
                    blueprint=blueprint,
                    directive=directive,
                    engine_override=engine_override,
                    workdir=workdir,
                    operator_layer=self._operator_layer,
                    env=env,
                    task=task,
                )

            stage_reports.append(report)
            emit("stage_finished", stage=stage.name, success=report.success)

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

        # Revert hook: when a committing flow fails, discard this demand's uncommitted
        # changes so the shared workdir is clean for the next demand (atomic semantics).
        # Gated on commit.enabled (never runs for a non-committing/commit=None flow)
        # and not success (never runs on a green flow, which commits instead).
        if (
            not skip_commit
            and flow.commit is not None
            and flow.commit.enabled
            and not success
            and len(stage_reports) > 0
        ):
            # `.alc/` is ALWAYS protected; the operator's commit.exclude only ADDS.
            exclude = (".alc/", *flow.commit.exclude)
            if revert_workdir(effective_workdir, exclude=exclude):
                print(
                    "▶ flow reverted — discarded the failed demand's changes.",
                    file=sys.stderr,
                    flush=True,
                )
            # revert_workdir returning None (not a repo / git missing) degrades
            # gracefully: the tree stays dirty as today; the flow is not crashed.

        # Terminal commit: only on a fully successful flow, and only when enabled.
        # Broken/unvalidated work never lands. Scoped to the flow's workdir.
        commit_sha: str | None = None
        if not skip_commit and success and flow.commit is not None and flow.commit.enabled:
            try:
                message = flow.commit.message.format(
                    name=flow.name,
                    task=(task.splitlines()[0] if task else ""),
                )
            except (KeyError, IndexError, ValueError) as _fmt_err:
                # A bad operator-supplied template must never crash a green flow.
                # Degrade gracefully: use the flow name as a safe fallback message.
                message = f"chore(cycle): {flow.name}"
                print(
                    f"[WARN] commit message template error ({_fmt_err!r}); "
                    f"falling back to: {message!r}",
                    file=sys.stderr,
                )
            # `.alc/` is ALWAYS protected; the operator's commit.exclude only ADDS.
            commit_sha = commit_workdir(
                effective_workdir, message, exclude=(".alc/", *flow.commit.exclude)
            )

        # Observe: close the flow with its outcome (and commit sha when created).
        if commit_sha is not None:
            emit("flow_finished", success=success, commit_sha=commit_sha)
        else:
            emit("flow_finished", success=success)

        return FlowReport(
            flow=flow.name,
            engine=engine_name,
            success=success,
            stages=stage_reports,
            scorecard=aggregate_scorecard,
            commit_sha=commit_sha,
        )
