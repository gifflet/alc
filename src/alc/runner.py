# runner.py — MandateRunner: ties the control plane together for one alc run.
# Composes the Single-Mandate directive, resolves the engine and Compute Tier,
# enforces the Policy Gate, and drives the Assurance Loop.
from __future__ import annotations

import contextlib
import subprocess
from pathlib import Path

from alc.assurance import AssuranceLoop
from alc.engine import Engine, EngineRequest
from alc.engines.registry import resolve_engine
from alc.events import emit
from alc.intake import resolve_checks
from alc.models import Blueprint, Diffstat, Manifest, RunReport
from alc.policy import has_errors, lint
from alc.runtime import RuntimeService
from alc.verifier import Verifier
from alc.worktree import allocate_free_ports, release_ports

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


def _diffstat(
    workdir: Path, changed_files: list[str], state_after: dict[str, str]
) -> Diffstat | None:
    """Return a Diffstat summarising the run's changes, or None when there is nothing to report.

    Line counts come from ``git diff --numstat HEAD`` (covers both staged and
    unstaged changes to tracked files against the commit the run started from);
    files_deleted comes from the porcelain status already captured in
    *state_after*. Degrades to None — never raises — when there are no changed
    files or the numstat diff cannot be read (e.g. a repo with no commits yet).
    """
    if not changed_files:
        return None

    try:
        result = subprocess.run(
            ["git", "-C", str(workdir), "diff", "--numstat", "HEAD"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None

    adds = 0
    dels = 0
    for line in result.stdout.splitlines():
        added, _, rest = line.partition("\t")
        deleted, _, _path = rest.partition("\t")
        if added.isdigit():
            adds += int(added)
        if deleted.isdigit():
            dels += int(deleted)

    files_deleted = sum(1 for path in changed_files if "D" in state_after.get(path, ""))
    return Diffstat(adds=adds, dels=dels, files_deleted=files_deleted)


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


def _resolve_runtime(
    manifest: Manifest,
    blueprint: Blueprint,
    directive: str,
    _env: dict[str, str],
    effective_workdir: Path,
    operator_layer: Path | None,
) -> tuple[str, contextlib.AbstractContextManager]:
    """Decide the run's runtime posture (MUTUALLY EXCLUSIVE) and wire it in.

    Three outcomes, in priority order:
      1. **CORE owns the service** — the Blueprint opts in (``needs_service``) AND
         the Manifest declares a ``service``. ALC picks the port (an already-injected
         ``PORT``/``ALC_PORT`` wins, else it allocates one), exposes ``ALC_BASE_URL``
         in ``_env``, appends the ``service-conventions`` prompt, and returns a
         ``RuntimeService`` so the app is up around the whole Assurance Loop.
      2. **Port-only (F1)** — no service, but a port is present in ``_env``. Appends
         the ``runtime-conventions`` prompt (existing behavior). Null context.
      3. **Nothing** — no service and no port. Directive/env untouched (byte-identical).

    Mutates ``_env`` in place (adds PORT/ALC_PORT/ALC_BASE_URL only in case 1 when a
    port was allocated here). Returns ``(directive, service_ctx)`` where ``service_ctx``
    is a null context except in case 1.
    """
    if blueprint.needs_service and manifest.service is not None and operator_layer is not None:
        from alc.prompts import resolve_prompt

        allocated: list[int] = []
        if "PORT" in _env:
            port = int(_env["PORT"])
        elif "ALC_PORT" in _env:
            port = int(_env["ALC_PORT"])
        else:
            allocated = allocate_free_ports(1)
            port = allocated[0]
            _env["PORT"] = str(port)
            _env["ALC_PORT"] = str(port)

        base_url = f"http://127.0.0.1:{port}"
        _env["ALC_BASE_URL"] = base_url
        directive = (
            directive
            + "\n\n---\n"
            + resolve_prompt("service-conventions", operator_layer, manifest)
        )
        service_ctx: contextlib.AbstractContextManager = _ServiceRun(
            manifest.service, effective_workdir, port, _env, allocated
        )
        return directive, service_ctx

    if operator_layer is not None and ("PORT" in _env or "ALC_PORT" in _env):
        from alc.prompts import resolve_prompt

        directive = (
            directive
            + "\n\n---\n"
            + resolve_prompt("runtime-conventions", operator_layer, manifest)
        )
    return directive, contextlib.nullcontext()


class _ServiceRun:
    """Bridges RuntimeService to ``with``: runs the app, releases any port ALC allocated.

    Wraps ``RuntimeService`` so a port allocated by ``_resolve_runtime`` is released
    on exit even when ``__enter__`` raises (app never came up) — the drain turns that
    RuntimeError into a failed report, so cleanup must not leak the reservation.
    """

    def __init__(
        self,
        service,
        workdir: Path,
        port: int,
        env: dict[str, str],
        allocated: list[int],
    ) -> None:
        self._svc = RuntimeService(service, workdir, port, env)
        self._allocated = allocated

    def __enter__(self):
        try:
            return self._svc.__enter__()
        except BaseException:
            release_ports(self._allocated)
            raise

    def __exit__(self, *exc) -> None:
        try:
            self._svc.__exit__(*exc)
        finally:
            release_ports(self._allocated)


def execute_mandate(
    manifest: Manifest,
    blueprint: Blueprint,
    directive: str,
    engine_override: str | None = None,
    workdir: Path | None = None,
    operator_layer: Path | None = None,
    env: dict[str, str] | None = None,
    task: str | None = None,
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
        task: Free-text task description recorded in the run event log. Not used
            for execution (the directive already carries it); None keeps the
            ``mandate_started`` payload's ``task`` field null.

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

    # Observe: announce the mandate (best-effort; no-op when no run log is bound).
    emit(
        "mandate_started",
        blueprint=blueprint.name,
        task=task,
        engine=engine_name,
        model=model,
    )

    # Resolve effective workdir once so the same value is used for snapshots and the request.
    effective_workdir = workdir or Path.cwd()

    # Resolve the run's runtime posture (mutually exclusive): the CORE owns the app
    # lifecycle (needs_service + manifest.service -> RuntimeService + service-conventions),
    # else the port-only F1 path (append runtime-conventions), else nothing (byte-identical).
    # A private COPY so `_resolve_runtime` can add ALC_BASE_URL (+ PORT/ALC_PORT when a
    # port is allocated here) without mutating the caller's env dict (the drain threads
    # ONE port_env through every stage — the service stage must not leak into siblings).
    _env = dict(env) if env else {}
    directive, service_ctx = _resolve_runtime(
        manifest, blueprint, directive, _env, effective_workdir, operator_layer
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
    verifier = Verifier(
        max_output_chars=manifest.check_output_chars, timeout_s=manifest.check_timeout_s
    )
    loop_kwargs: dict = {}
    if blueprint.max_repairs is not None:
        loop_kwargs["max_repairs"] = blueprint.max_repairs
    if operator_layer is not None:
        # Resolve the reserved `repair` prompt through the override registry.
        from alc.prompts import resolve_prompt

        loop_kwargs["repair_template"] = resolve_prompt("repair", operator_layer, manifest)
    loop = AssuranceLoop(engine=engine, verifier=verifier, **loop_kwargs)
    # When the CORE owns the service, `service_ctx` starts the app (and blocks until
    # it is healthy) before the loop and tears it down after, so it is up for the whole
    # Act + repair + verify. Otherwise `service_ctx` is a null context (no-op).
    with service_ctx:
        report = loop.run(request=request, checks=resolve_checks(manifest, blueprint))

    # Snapshot the git state after the Assurance Loop and compute changed paths.
    state_after = _git_state(effective_workdir)
    if state_before is None or state_after is None:
        changed_files: list[str] = []
        diffstat: Diffstat | None = None
    else:
        changed_files = _changed_between(state_before, state_after)
        diffstat = _diffstat(effective_workdir, changed_files, state_after)

    # Patch the report's blueprint field to the real name (not the truncated directive).
    final_report = RunReport(
        blueprint=blueprint.name,
        engine=report.engine,
        success=report.success,
        attempts=report.attempts,
        scorecard=report.scorecard,
        output_text=report.output_text,
        changed_files=changed_files,
        diffstat=diffstat,
        usage=report.usage,
        archetype=blueprint.archetype,
    )

    # Observe: close the mandate with its outcome and scorecard.
    emit(
        "mandate_finished",
        success=final_report.success,
        attempts=len(final_report.attempts),
        scorecard=final_report.scorecard.model_dump(),
    )
    return final_report


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
            task=task,
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
