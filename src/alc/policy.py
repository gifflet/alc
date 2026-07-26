# policy.py — Policy Gate: conformance rules for the Operator Layer.
# Lints a Manifest + its Blueprints and returns Violations with severity error/warn.
# An error violation blocks alc run; a warn is advisory only.
from __future__ import annotations

import subprocess
from dataclasses import dataclass

from pathlib import Path

from alc.intake import is_smoke_only, resolve_checks
from alc.models import Blueprint, FlowDefinition, LoopDefinition, Manifest


@dataclass
class Violation:
    """A single Policy Gate finding."""

    rule: str
    severity: str   # "error" or "warn"
    message: str


_VALID_PERMISSION_MODES: frozenset[str] = frozenset(
    {"acceptEdits", "auto", "bypassPermissions", "default"}
)

# Public (not underscore-prefixed): also imported by stagepolicy.py, whose
# stage-mix rules (roadmap-phase-4.md T5) validate against the same set.
VALID_ARCHETYPES: frozenset[str] = frozenset(
    {"prototyper", "builder", "sweeper", "grower", "maintainer"}
)

# The literal smoke fallback every pack Blueprint keeps (packs.py) so a check_set
# alone can never resolve a Blueprint to zero checks. Rule 11 below detects when
# that fallback is ALL that ran.


def lint(manifest: Manifest, blueprints: list[Blueprint]) -> list[Violation]:
    """Run all Policy Gate rules and return every Violation found.

    Rules (from mvp.md):
    1. Blueprint resolves to >= 1 check          (error) — no Assurance Loop otherwise.
    2. Blueprint has exactly one name/purpose    (error) — Single Mandate.
    3. Blueprint declares a report spec          (warn)  — structured output.
    4. manifest.default_engine in manifest.engines   (error) — resolvable execution plane.
    5. Every Compute Tier maps the referenced engine (error) — model resolvable.
    6. Blueprint max_repairs, when set, is >= 0  (error) — valid repair budget.
    7. Blueprint check_set names a declared set  (error) — resolvable check set.
    8. Blueprint permission_mode, when set, is a recognised claude-code value
                                                 (error) — prevents silent misconfiguration.
    9. Blueprint timeout_s, when set, is > 0     (warn)  — a non-positive value kills
                                                            the engine turn immediately.
    10. Blueprint archetype, when set, is a recognised value
                                                 (warn)  — catches a typo'd label; the
                                                            field has zero runtime effect.
    11. Blueprint check_set is set, name != 'plan', and resolved checks are
        nothing but the smoke placeholder     (warn)  — its check_set is
                                                          currently empty (no
                                                          matching tool binary
                                                          on PATH); see `alc
                                                          checks audit`.
    12. Blueprint protect globs, when declared, are well-formed relative
        patterns                                    (error) — an absolute path
                                                          or one that escapes the
                                                          workdir via '..' can
                                                          never match a changed
                                                          -file path, silently
                                                          protecting nothing.
    13. manifest.quarantined_checks, for each name listed  (warn) — PERMANENT for
                                                          as long as it is listed
                                                          (roadmap-phase-3.md T11):
                                                          a quarantine that the
                                                          lint stays silent about
                                                          would be invisible debt.
    14. A resolved check that declares 'metric' must also declare 'direction'
                                                 (error) — roadmap-phase-4.md T1:
                                                          the Verifier cannot judge
                                                          a number without knowing
                                                          which way is better. Kept
                                                          as a gate rule (not a
                                                          pydantic validator) so the
                                                          message carries the owning
                                                          Blueprint's name.
    15. Blueprint sets allow_check_config: true   (warn)  — it waives the
                                                          check-config-integrity
                                                          guard (may edit files that
                                                          define its own checks
                                                          without failing the run).
                                                          PERMANENT while set, like
                                                          rule 13's quarantine: a
                                                          standing exception the
                                                          lint stays silent about is
                                                          invisible attack surface.

    Rule 1 is the ONE relaxation in the whole gate (roadmap-phase-3.md T1): a
    Blueprint declaring `mode: spike` still gets flagged for having no checks,
    but only as a warn — the exception is fenced everywhere else (the runner
    forces isolation/zero-repairs/no-commit; see runner.py and rule 4 of
    lint_flow below).

    Resolved checks = the named check_set's checks (if any) plus the Blueprint's own,
    so a Blueprint that only references a check_set still satisfies rule 1.

    Rule 11 is deliberately scoped to Blueprints that OPT INTO a check_set: the
    default `alc init` layer never sets check_set (even on a stack-less project,
    where chore/bug/feature also resolve to only the smoke placeholder), so it
    stays exempt without a separate check — and `plan` is exempt outright, since a
    planning stage legitimately produces no executable code.
    """
    violations: list[Violation] = []

    # Rule 13: every quarantined check is a PERMANENT warn for as long as it is
    # listed — a quarantine the lint stays silent about would be invisible debt.
    for name in manifest.quarantined_checks:
        violations.append(
            Violation(
                rule="quarantined-check",
                severity="warn",
                message=(
                    f"Check '{name}' is quarantined (manifest.quarantined_checks) — "
                    "it still runs but cannot fail a run. Remove it from the list "
                    "once it is reliable again."
                ),
            )
        )

    # Rule 4: default_engine must be declared in manifest.engines.
    if manifest.default_engine not in manifest.engines:
        violations.append(
            Violation(
                rule="default_engine_resolvable",
                severity="error",
                message=(
                    f"manifest.default_engine '{manifest.default_engine}' is not declared "
                    f"in manifest.engines (available: {list(manifest.engines)})"
                ),
            )
        )

    # Rule 5: every compute tier must map every engine referenced in blueprints.
    # For the MVP we check that all tiers map the default_engine at minimum.
    for tier_name, tier_map in manifest.compute_tiers.items():
        if manifest.default_engine not in tier_map:
            violations.append(
                Violation(
                    rule="compute_tier_maps_engine",
                    severity="error",
                    message=(
                        f"Compute Tier '{tier_name}' does not map engine "
                        f"'{manifest.default_engine}'."
                    ),
                )
            )

    for bp in blueprints:
        # Rule 7: check_set, when set, must name a set declared in the Manifest.
        if bp.check_set is not None and bp.check_set not in manifest.check_sets:
            violations.append(
                Violation(
                    rule="blueprint-check-set-exists",
                    severity="error",
                    message=(
                        f"Blueprint '{bp.name}' references check_set '{bp.check_set}' "
                        f"which is not declared in manifest.check_sets "
                        f"(available: {sorted(manifest.check_sets)})."
                    ),
                )
            )

        # Rule 1: blueprint must resolve to at least one check (own checks + check_set).
        # `mode: spike` is the ONE relaxation of this gate: still flagged, but only
        # as a warn, never blocking the run (roadmap-phase-3.md T1).
        if not resolve_checks(manifest, bp):
            violations.append(
                Violation(
                    rule="blueprint_has_checks",
                    severity="warn" if bp.mode == "spike" else "error",
                    message=(
                        f"Blueprint '{bp.name}' declares no checks — "
                        "an Assurance Loop without checks provides no guarantee."
                    ),
                )
            )

        # Rule 2: blueprint must have a non-empty name and purpose (Single Mandate).
        if not bp.name or not bp.purpose:
            violations.append(
                Violation(
                    rule="blueprint_single_mandate",
                    severity="error",
                    message=(
                        f"Blueprint '{bp.name}' is missing a name or purpose — "
                        "every Blueprint must declare exactly one mandate."
                    ),
                )
            )

        # Rule 3: blueprint should declare a report spec.
        if bp.report is None:
            violations.append(
                Violation(
                    rule="blueprint_has_report",
                    severity="warn",
                    message=(
                        f"Blueprint '{bp.name}' does not declare a report spec — "
                        "structured output aids parsing and traceability."
                    ),
                )
            )

        # Rule 6: max_repairs, when declared, must be >= 0.
        if bp.max_repairs is not None and bp.max_repairs < 0:
            violations.append(
                Violation(
                    rule="blueprint-max-repairs-valid",
                    severity="error",
                    message=(
                        f"Blueprint '{bp.name}' declares max_repairs={bp.max_repairs} — "
                        "repair budget must be >= 0 (0 = one shot, no repair)."
                    ),
                )
            )

        # Rule 8: permission_mode, when declared, must be a recognised value.
        if bp.permission_mode is not None and bp.permission_mode not in _VALID_PERMISSION_MODES:
            violations.append(
                Violation(
                    rule="blueprint-permission-mode-valid",
                    severity="error",
                    message=(
                        f"Blueprint '{bp.name}' declares permission_mode='{bp.permission_mode}' "
                        f"which is not a recognised value "
                        f"(allowed: {sorted(_VALID_PERMISSION_MODES)})."
                    ),
                )
            )

        # Rule 9: timeout_s, when declared, should be positive (advisory).
        if bp.timeout_s is not None and bp.timeout_s <= 0:
            violations.append(
                Violation(
                    rule="blueprint-timeout-positive",
                    severity="warn",
                    message=(
                        f"Blueprint '{bp.name}' declares timeout_s={bp.timeout_s} — "
                        "a non-positive timeout kills the engine turn immediately."
                    ),
                )
            )

        # Rule 10: archetype, when declared, should be a recognised value (advisory).
        if bp.archetype is not None and bp.archetype not in VALID_ARCHETYPES:
            violations.append(
                Violation(
                    rule="blueprint-archetype-known",
                    severity="warn",
                    message=(
                        f"Blueprint '{bp.name}' declares archetype='{bp.archetype}' "
                        f"which is not a recognised value "
                        f"(known: {sorted(VALID_ARCHETYPES)})."
                    ),
                )
            )

        # Rule 11: an execution Blueprint (not `plan`) that opts into a check_set
        # but resolves to nothing but the smoke placeholder — its check_set is
        # currently empty (advisory; `alc checks audit` explains why).
        if (
            bp.check_set is not None
            and is_smoke_only(manifest, bp)
        ):
            violations.append(
                Violation(
                    rule="blueprint-checks-smoke-only",
                    severity="warn",
                    message=(
                        f"Blueprint '{bp.name}' declares check_set '{bp.check_set}' but "
                        "resolves to nothing but the smoke placeholder — check_set "
                        f"'{bp.check_set}' is currently empty (no matching tool binary "
                        "on PATH). Run `alc checks audit` to see what would become "
                        "available."
                    ),
                )
            )

        # Rule 14: a metric check without a direction cannot be judged — the
        # Verifier would have no way to know whether a bigger or a smaller
        # number is the regression.
        for check in resolve_checks(manifest, bp):
            if check.metric is not None and check.direction is None:
                violations.append(
                    Violation(
                        rule="metric-requires-direction",
                        severity="error",
                        message=(
                            f"Blueprint '{bp.name}' check '{check.name}' declares "
                            "'metric' without 'direction' — set direction: "
                            "lower_is_better or higher_is_better."
                        ),
                    )
                )

        # Rule 12: protect globs, when declared, must be well-formed relative
        # patterns. A changed-file path is always workdir-relative (git status
        # output), so an absolute glob or one escaping the workdir via '..' can
        # never match anything — a silent no-op that defeats the whole point of
        # declaring `protect:` in the first place.
        for glob in bp.protect:
            reason: str | None = None
            if not glob.strip():
                reason = "empty"
            elif Path(glob).is_absolute():
                reason = "an absolute path"
            elif ".." in Path(glob).parts:
                reason = "escapes the workdir via '..'"
            if reason is not None:
                violations.append(
                    Violation(
                        rule="blueprint-protect-globs-valid",
                        severity="error",
                        message=(
                            f"Blueprint '{bp.name}' declares protect glob '{glob}' "
                            f"which is {reason} — it can never match a changed-file "
                            "path (always workdir-relative)."
                        ),
                    )
                )

        # Rule 15: allow_check_config waives the check-config-integrity guard —
        # legitimate for a maintenance Blueprint whose job IS to edit lint/test
        # config, but a standing exception that must stay in view for as long as it
        # is set (a run under it can pass a failing check by editing the check's own
        # config). Permanent-while-set, mirroring rule 13's quarantine precedent.
        if bp.allow_check_config:
            violations.append(
                Violation(
                    rule="blueprint-allows-check-config",
                    severity="warn",
                    message=(
                        f"Blueprint '{bp.name}' sets allow_check_config: true — it may "
                        "edit files that define its own checks without failing the "
                        "run. Legitimate for check maintenance; remove it once the "
                        "maintenance is done so the guard protects this Blueprint again."
                    ),
                )
            )

    return violations


def has_errors(violations: list[Violation]) -> bool:
    """Return True if any violation has severity 'error'."""
    return any(v.severity == "error" for v in violations)


def lint_flow(
    flow: FlowDefinition,
    available_blueprints: set[str],
    available_specialists: set[str] | None = None,
    stage_blueprints: dict[str, Blueprint] | None = None,
) -> list[Violation]:
    """Run Policy Gate rules specific to a FlowDefinition.

    Rules:
    1. Flow must declare at least one stage              (error) — no Assurance Loop otherwise.
    2. Every blueprint stage's blueprint must exist      (error) — resolvable execution.
    3. Every specialist stage's specialist must exist    (error) — resolvable execution.
    4. A stage whose effective Blueprint declares mode: spike, combined with an
       enabled commit block                              (error) — the spike
       exception must never become a delivery path (roadmap-phase-3.md T1).
       Only checked when *stage_blueprints* is supplied; omitting it (existing
       call sites) skips rule 4 entirely, byte-identical to before it existed.
    5. A stage's derive_checks.shell_template must contain the literal
       '{value}' placeholder                             (error) — otherwise
                                                            nothing is ever
                                                            interpolated
                                                            (roadmap-phase-4.md T9).
    6. A stage's derive_checks.from_stage must name a stage that appears
       EARLIER in the same Flow                           (error) — a forward
                                                            or self reference
                                                            can never have a
                                                            report to read
                                                            (roadmap-phase-4.md T9).

    The exactly-one-of blueprint/specialist rule (and verify_only requiring a
    blueprint) is already enforced by the FlowStage pydantic validator at intake.

    Args:
        flow: The FlowDefinition to validate.
        available_blueprints: Set of blueprint names present in the Operator Layer.
        available_specialists: Set of specialist names present in the Operator
            Layer. None is treated as an empty set (no specialists available).
        stage_blueprints: {stage name: effective Blueprint}, when the caller has
            already resolved one per stage (FlowRunner does, for the Policy
            Gate). None skips rule 4.

    Returns:
        List of Violations (may be empty).
    """
    available_specialists = available_specialists or set()
    violations: list[Violation] = []

    # Rule 1: flow must have at least one stage.
    if not flow.stages:
        violations.append(
            Violation(
                rule="flow-has-stages",
                severity="error",
                message=(
                    f"Flow '{flow.name}' declares no stages — "
                    "a Flow without stages provides no pipeline."
                ),
            )
        )
        return violations  # no point checking stage refs if there are none

    commit_enabled = flow.commit is not None and flow.commit.enabled

    # Rule 2/3: every stage's referenced blueprint or specialist must exist.
    # Rule 4: a spike-mode stage may not sit inside a committing Flow.
    # Rules 5/6: a derive_checks stage's template and upstream reference.
    for idx, stage in enumerate(flow.stages):
        if stage.blueprint is not None and stage.blueprint not in available_blueprints:
            violations.append(
                Violation(
                    rule="flow-blueprint-exists",
                    severity="error",
                    message=(
                        f"Flow '{flow.name}', stage '{stage.name}': blueprint "
                        f"'{stage.blueprint}' does not exist in the Operator Layer "
                        f"(available: {sorted(available_blueprints)})."
                    ),
                )
            )
        if stage.specialist is not None and stage.specialist not in available_specialists:
            violations.append(
                Violation(
                    rule="flow-specialist-exists",
                    severity="error",
                    message=(
                        f"Flow '{flow.name}', stage '{stage.name}': specialist "
                        f"'{stage.specialist}' does not exist in the Operator Layer "
                        f"(available: {sorted(available_specialists)})."
                    ),
                )
            )

        if stage_blueprints is not None and commit_enabled:
            bp = stage_blueprints.get(stage.name)
            if bp is not None and bp.mode == "spike":
                violations.append(
                    Violation(
                        rule="flow-spike-forbids-commit",
                        severity="error",
                        message=(
                            f"Flow '{flow.name}', stage '{stage.name}': blueprint "
                            f"'{bp.name}' declares mode: spike, which cannot be "
                            "combined with an enabled commit block — the spike "
                            "exception must never become a delivery path."
                        ),
                    )
                )

        if stage.derive_checks is not None:
            dc = stage.derive_checks
            # Rule 5: the template must actually interpolate something.
            if "{value}" not in dc.shell_template:
                violations.append(
                    Violation(
                        rule="flow-derive-checks-template-has-value",
                        severity="error",
                        message=(
                            f"Flow '{flow.name}', stage '{stage.name}': "
                            "derive_checks.shell_template does not contain the "
                            "literal '{value}' placeholder — nothing would ever "
                            "be interpolated into it."
                        ),
                    )
                )
            # Rule 6: from_stage must be a stage that already ran by this point.
            earlier_stage_names = {s.name for s in flow.stages[:idx]}
            if dc.from_stage not in earlier_stage_names:
                violations.append(
                    Violation(
                        rule="flow-derive-checks-from-stage-earlier",
                        severity="error",
                        message=(
                            f"Flow '{flow.name}', stage '{stage.name}': "
                            f"derive_checks.from_stage '{dc.from_stage}' does not "
                            "name a stage that appears earlier in the same Flow "
                            f"(earlier stages: {sorted(earlier_stage_names)})."
                        ),
                    )
                )

    return violations


def validate_loop(
    manifest: Manifest, operator_layer: Path, loop_def: LoopDefinition
) -> list[Violation]:
    """Run Policy Gate rules specific to a LoopDefinition.

    The numeric constraints (max_cycles > 0, budget.max > 0, max_consecutive >= 1,
    valid budget unit) are already enforced by the pydantic validators at load
    time, so the only reference this checks is the replenish target: a
    specialist/plan-kind replenish must name a Specialist file that exists, and
    a flow/signals/regression-kind replenish must name a Flow file that exists.

    Args:
        manifest: The loaded Manifest (provides specialists_dir).
        operator_layer: Path to the ``.alc/`` directory.
        loop_def: The LoopDefinition to validate.

    Returns:
        List of Violations (may be empty).
    """
    violations: list[Violation] = []

    replenish = loop_def.replenish
    if replenish is not None and replenish.kind in ("specialist", "plan"):
        specialists_dir = operator_layer.parent / manifest.specialists_dir
        ref = replenish.ref
        if not ref or not (specialists_dir / f"{ref}.yaml").exists():
            violations.append(
                Violation(
                    rule="loop-replenish-specialist-exists",
                    severity="error",
                    message=(
                        f"Loop '{loop_def.name}' replenish references specialist "
                        f"'{ref}' which does not exist in {specialists_dir}."
                    ),
                )
            )

    if replenish is not None and replenish.kind in ("flow", "signals", "regression"):
        flows_dir = operator_layer.parent / manifest.flows_dir
        ref = replenish.ref
        if not ref or not (flows_dir / f"{ref}.yaml").exists():
            violations.append(
                Violation(
                    rule="loop-replenish-flow-exists",
                    severity="error",
                    message=(
                        f"Loop '{loop_def.name}' replenish references flow "
                        f"'{ref}' which does not exist in {flows_dir}."
                    ),
                )
            )

    return violations


def validate_prompts(
    manifest: Manifest,
    operator_layer: Path,
    blueprints: list[Blueprint],
) -> list[Violation]:
    """Run Policy Gate rules for the keyed prompt-override store (prompts_dir).

    Rules:
    1. Every override file whose stem is a RESERVED name must (a) contain all of that
       prompt's required placeholders and (b) render via ``.format()`` without a stray
       unescaped brace                                   (error) — safe by construction.
    2. Every ``{{prompt:X}}`` reference in a Blueprint workflow must resolve to an
       existing prompt (reserved default or a free file)  (error).
    3. Every ``{{prompt:X}}`` reference inside any prompt file in prompts_dir
       (reserved overrides AND free prompts) must resolve  (error) — so a dangling
       include is caught at lint time whether it lives in a workflow or a prompt.
       NOTE: a reserved-prompt OVERRIDE is used verbatim at its call site and is NOT
       itself run through expand_includes; this rule only lints its include refs.

    Args:
        manifest: The loaded Manifest (provides prompts_dir).
        operator_layer: Path to the ``.alc/`` directory.
        blueprints: Every Blueprint in the Operator Layer (their workflows are scanned).
            Flow definitions carry no free-text workflow — their stages reference
            Blueprints, already covered — so only Blueprint workflows hold include tokens.

    Returns:
        List of Violations (may be empty).
    """
    from alc.prompts import (
        _DEFAULT_PROMPTS,
        include_refs,
        override_format_error,
        resolve_prompt,
        validate_prompt_override,
    )

    violations: list[Violation] = []

    # Rule 1 + 3: scan every prompt file once. Reserved overrides get the
    # placeholder/formattable checks; EVERY file's include refs are checked.
    prompts_dir = operator_layer.parent / manifest.prompts_dir
    if prompts_dir.exists():
        for md_file in sorted(prompts_dir.glob("*.md")):
            name = md_file.stem
            text = md_file.read_text()

            # Rule 1: reserved override files must keep their required
            # placeholders AND render via .format() without a stray brace.
            if name in _DEFAULT_PROMPTS:
                missing = validate_prompt_override(name, text)
                if missing:
                    violations.append(
                        Violation(
                            rule="prompt-override-placeholders",
                            severity="error",
                            message=(
                                f"Prompt override '{name}' is missing required "
                                f"placeholder(s): {missing}."
                            ),
                        )
                    )
                fmt_error = override_format_error(name, text)
                if fmt_error:
                    violations.append(
                        Violation(
                            rule="prompt-override-formattable",
                            severity="error",
                            message=(
                                f"Prompt override '{name}' cannot be rendered: {fmt_error}"
                            ),
                        )
                    )

            # Rule 3: every {{prompt:X}} reference in the file itself must resolve.
            for ref in include_refs(text):
                try:
                    resolve_prompt(ref, operator_layer, manifest)
                except KeyError:
                    violations.append(
                        Violation(
                            rule="prompt-include-resolves",
                            severity="error",
                            message=(
                                f"Prompt '{name}' references prompt '{{{{prompt:{ref}}}}}' "
                                f"which does not resolve to a reserved default or a "
                                f"prompt file in {prompts_dir}."
                            ),
                        )
                    )

    # Rule 2: every {{prompt:X}} reference in a Blueprint workflow must resolve.
    for bp in blueprints:
        for ref in include_refs(bp.workflow):
            try:
                resolve_prompt(ref, operator_layer, manifest)
            except KeyError:
                violations.append(
                    Violation(
                        rule="prompt-include-resolves",
                        severity="error",
                        message=(
                            f"Blueprint '{bp.name}' references prompt '{{{{prompt:{ref}}}}}' "
                            f"which does not resolve to a reserved default or a "
                            f"prompt file in {prompts_dir}."
                        ),
                    )
                )

    return violations


def validate_provisions(manifest: Manifest, project_root: Path) -> list[Violation]:
    """Run Policy Gate rules for manifest.worktree_provision.

    Rule (error): a provisioned path must be GITIGNORED — provisioning a TRACKED
    path would leak the runtime dep into the demand's exit-commit. Best-effort:
    ``git -C <project_root> ls-files --error-unmatch <path>`` exiting 0 means the
    path is tracked -> violation ``worktree-provision-tracked``.

    If git is unavailable or the project root is not a repository, the check is
    skipped entirely (no false errors).

    Args:
        manifest: The loaded Manifest (provides worktree_provision).
        project_root: The project root (the parent of the ``.alc/`` directory).

    Returns:
        List of Violations (may be empty).
    """
    violations: list[Violation] = []
    if not manifest.worktree_provision:
        return violations

    for spec in manifest.worktree_provision:
        try:
            result = subprocess.run(
                ["git", "-C", str(project_root), "ls-files", "--error-unmatch", spec.path],
                capture_output=True,
            )
        except FileNotFoundError:
            return violations  # git not installed -> skip the whole check
        # A non-zero exit means "not tracked" OR "not a git repo"; either way,
        # only a clean exit (0 = tracked) is a violation.
        if result.returncode == 0:
            violations.append(
                Violation(
                    rule="worktree-provision-tracked",
                    severity="error",
                    message=(
                        f"worktree_provision path '{spec.path}' is tracked by git — "
                        "provisioning a tracked path would leak the runtime dep into "
                        "the demand's commit. Provision gitignored runtime deps only."
                    ),
                )
            )

    return violations
