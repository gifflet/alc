# runner.py — MandateRunner: ties the control plane together for one alc run.
# Composes the Single-Mandate directive, resolves the engine and Compute Tier,
# enforces the Policy Gate, and drives the Assurance Loop.
from __future__ import annotations

from pathlib import Path

from alc.assurance import AssuranceLoop
from alc.engine import Engine, EngineRequest
from alc.engines.registry import resolve_engine
from alc.models import Blueprint, Manifest, RunReport
from alc.policy import has_errors, lint
from alc.verifier import Verifier

# Brief context header prepended to the directive to satisfy the Context Budget.
_CONTEXT_HEADER_TEMPLATE = """\
# ALC Single-Mandate Run
Blueprint: {blueprint_name}
Purpose:   {purpose}
Task:      {task}

---
"""


class PolicyViolationError(RuntimeError):
    """Raised when the Policy Gate finds error-level violations, blocking the run."""


def execute_mandate(
    manifest: Manifest,
    blueprint: Blueprint,
    directive: str,
    engine_override: str | None = None,
    workdir: Path | None = None,
) -> RunReport:
    """Resolve the engine, build the EngineRequest, and run the Assurance Loop.

    This is the shared engine+assurance helper used by both MandateRunner and
    FlowRunner. It does NOT run the Policy Gate — that is the caller's responsibility.

    Args:
        manifest: The loaded Manifest (provides engines config and compute tiers).
        blueprint: The Blueprint that declares checks, compute tier, and report schema.
        directive: The fully composed Single-Mandate directive string.
        engine_override: If set, use this engine name instead of manifest.default_engine.
        workdir: Directory to run checks in. Defaults to Path.cwd().
            NOTE: Per-stage worktree isolation (one worktree per Flow stage) is deferred
            to the Detached maturity stage. All stages share cwd for the MVP.

    Returns:
        RunReport with blueprint=blueprint.name and full Scorecard.
    """
    # Resolve engine.
    engine_name = engine_override or manifest.default_engine
    engine: Engine = resolve_engine(engine_name, manifest.engines)

    # Resolve model from Compute Tier.
    model: str | None = None
    tier = manifest.compute_tiers.get(blueprint.compute_tier)
    if tier:
        model = tier.get(engine_name)

    # Build the EngineRequest.
    request = EngineRequest(
        directive=directive,
        workdir=workdir or Path.cwd(),
        model=model,
    )

    # Run the Assurance Loop — use Blueprint's repair budget when set, else keep default.
    verifier = Verifier()
    loop_kwargs: dict = {}
    if blueprint.max_repairs is not None:
        loop_kwargs["max_repairs"] = blueprint.max_repairs
    loop = AssuranceLoop(engine=engine, verifier=verifier, **loop_kwargs)
    report = loop.run(request=request, checks=blueprint.checks)

    # Patch the report's blueprint field to the real name (not the truncated directive).
    return RunReport(
        blueprint=blueprint.name,
        engine=report.engine,
        success=report.success,
        attempts=report.attempts,
        scorecard=report.scorecard,
        output_text=report.output_text,
    )


class MandateRunner:
    """Composes and executes one Single-Mandate directive end to end.

    Resolves the engine and model, enforces the Policy Gate, then runs the
    Assurance Loop (Act -> Verify -> Repair).
    """

    def __init__(self, manifest: Manifest, operator_layer: Path) -> None:
        self._manifest = manifest
        self._operator_layer = operator_layer

    def run(
        self,
        blueprint: Blueprint,
        task: str,
        engine_override: str | None = None,
        workdir: Path | None = None,
        extra_context: str | None = None,
    ) -> RunReport:
        """Execute one task against the given Blueprint.

        Args:
            blueprint: The loaded Blueprint describing workflow, checks, and Compute Tier.
            task: The free-text task description provided by the operator.
            engine_override: If set, use this engine name instead of manifest.default_engine.
            workdir: Directory to run checks in. Defaults to Path.cwd() when None.
                     Pass an IsolatedWorktree path to confine agent edits to that tree.
            extra_context: Optional primed context string (Primer text, bundle summary, or
                           both joined). Injected into the directive when truthy; default
                           None leaves behavior unchanged (Context Budget Trim move).

        Returns:
            RunReport with full attempt history and Scorecard.

        Raises:
            PolicyViolationError: If the Policy Gate finds error-level violations.
            KeyError: If the engine or model cannot be resolved.
        """
        # Policy Gate: lint and refuse on error violations.
        violations = lint(self._manifest, [blueprint])
        if has_errors(violations):
            error_msgs = [v.message for v in violations if v.severity == "error"]
            raise PolicyViolationError(
                "Policy Gate blocked this run:\n" + "\n".join(f"  - {m}" for m in error_msgs)
            )

        # Compose the Single-Mandate directive.
        directive = self._compose_directive(blueprint, task, extra_context=extra_context)

        return execute_mandate(self._manifest, blueprint, directive, engine_override, workdir)

    def _compose_directive(
        self,
        blueprint: Blueprint,
        task: str,
        extra_context: str | None = None,
    ) -> str:
        """Compose the full Single-Mandate directive from the Blueprint and task.

        When extra_context is truthy, a '## Primed context' section is inserted
        after the header and before the Blueprint workflow (Context Budget Trim move).
        """
        header = _CONTEXT_HEADER_TEMPLATE.format(
            blueprint_name=blueprint.name,
            purpose=blueprint.purpose,
            task=task,
        )
        if extra_context:
            primed_section = "## Primed context\n\n" + extra_context + "\n\n---\n"
            return header + primed_section + blueprint.workflow
        return header + blueprint.workflow
