# runner.py — MandateRunner: ties the control plane together for one alc run.
# Composes the Single-Mandate directive, resolves the engine and Compute Tier,
# enforces the Policy Gate, and drives the Assurance Loop.
from __future__ import annotations

import subprocess
from pathlib import Path

from alc.assurance import AssuranceLoop
from alc.engine import Engine, EngineRequest
from alc.engines.registry import resolve_engine
from alc.intake import resolve_checks
from alc.models import Blueprint, Manifest, RunReport
from alc.policy import has_errors, lint
from alc.verifier import Verifier

def _git_state(workdir: Path) -> dict[str, str] | None:
    """Return a {path: status} map for the given workdir, or None if not a git work tree.

    Runs ``git status --porcelain -uall`` and parses every output line into a
    dict keyed by the relative file path with the two-character porcelain status
    code as the value.  Returns None when workdir is not inside a git repo or
    when git is not available.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(workdir), "status", "--porcelain", "-uall"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        # git not installed
        return None

    if result.returncode != 0:
        return None

    state: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        # Porcelain v1: XY SPACE path  (XY = two-char status, cols 0-1; path starts at col 3)
        status = line[:2]
        path = line[3:].strip()
        state[path] = status
    return state


def _changed_between(
    before: dict[str, str],
    after: dict[str, str],
) -> list[str]:
    """Return sorted paths that are new in *after* or whose status changed since *before*.

    A path is considered changed when it appears for the first time in *after*,
    or when its porcelain status code differs from the one recorded in *before*.
    """
    changed: list[str] = []
    for path, status in after.items():
        if path not in before or before[path] != status:
            changed.append(path)
    return sorted(changed)


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
    operator_layer: Path | None = None,
    env: dict[str, str] | None = None,
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
        operator_layer: Path to the ``.alc/`` directory. When set, the ``repair``
            prompt is resolved through the override registry (so an operator override
            replaces the built-in). None keeps the embedded default (backward compat).
        env: Extra environment variables to inject into the engine turn (the adapter
            merges them over os.environ). None -> ``{}`` -> byte-identical to today.

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

    # Resolve effective workdir once so the same value is used for snapshots and the request.
    effective_workdir = workdir or Path.cwd()

    # Runtime conventions: when ALC has injected a network port into this run's env (a
    # worktree port allocation), append the embedded `runtime-conventions` prompt so the
    # agent binds ALC's assigned $PORT/$ALC_PORT instead of hardcoding one. Core-owned
    # default, overridable via the prompt store. A no-op when no port was injected, so
    # non-worktree/serial runs stay byte-identical.
    _env = env or {}
    if operator_layer is not None and ("PORT" in _env or "ALC_PORT" in _env):
        from alc.prompts import resolve_prompt

        directive = (
            directive
            + "\n\n---\n"
            + resolve_prompt("runtime-conventions", operator_layer, manifest)
        )

    # Per-turn kill timeout: a Blueprint override wins, else the manifest default.
    timeout_s = (
        blueprint.timeout_s
        if blueprint.timeout_s is not None
        else manifest.default_timeout_s
    )
    # Build the EngineRequest. permission_mode is an opt-in Blueprint override
    # threaded through to the engine adapter without interpretation here (DIP).
    request = EngineRequest(
        directive=directive,
        workdir=effective_workdir,
        model=model,
        permission_mode=blueprint.permission_mode,
        timeout_s=timeout_s,
        env=_env,
    )

    # Snapshot the git state before the Assurance Loop.
    state_before = _git_state(effective_workdir)

    # Run the Assurance Loop — use Blueprint's repair budget when set, else keep default.
    verifier = Verifier(max_output_chars=manifest.check_output_chars)
    loop_kwargs: dict = {}
    if blueprint.max_repairs is not None:
        loop_kwargs["max_repairs"] = blueprint.max_repairs
    if operator_layer is not None:
        # Resolve the reserved `repair` prompt through the override registry.
        from alc.prompts import resolve_prompt

        loop_kwargs["repair_template"] = resolve_prompt("repair", operator_layer, manifest)
    loop = AssuranceLoop(engine=engine, verifier=verifier, **loop_kwargs)
    report = loop.run(request=request, checks=resolve_checks(manifest, blueprint))

    # Snapshot the git state after the Assurance Loop and compute changed paths.
    state_after = _git_state(effective_workdir)
    if state_before is None or state_after is None:
        changed_files: list[str] = []
    else:
        changed_files = _changed_between(state_before, state_after)

    # Patch the report's blueprint field to the real name (not the truncated directive).
    return RunReport(
        blueprint=blueprint.name,
        engine=report.engine,
        success=report.success,
        attempts=report.attempts,
        scorecard=report.scorecard,
        output_text=report.output_text,
        changed_files=changed_files,
        usage=report.usage,
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

        # Compose the Single-Mandate directive, then expand any {{prompt:<name>}}
        # includes (compose stays pure; expansion happens here where we have the
        # operator_layer). A workflow with no include token is returned unchanged.
        from alc.prompts import expand_includes

        directive = self._compose_directive(blueprint, task, extra_context=extra_context)
        directive = expand_includes(directive, self._operator_layer, self._manifest)

        return execute_mandate(
            self._manifest,
            blueprint,
            directive,
            engine_override,
            workdir,
            self._operator_layer,
        )

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
