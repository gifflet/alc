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

_VALID_ARCHETYPES: frozenset[str] = frozenset(
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

    Resolved checks = the named check_set's checks (if any) plus the Blueprint's own,
    so a Blueprint that only references a check_set still satisfies rule 1.

    Rule 11 is deliberately scoped to Blueprints that OPT INTO a check_set: the
    default `alc init` layer never sets check_set (even on a stack-less project,
    where chore/bug/feature also resolve to only the smoke placeholder), so it
    stays exempt without a separate check — and `plan` is exempt outright, since a
    planning stage legitimately produces no executable code.
    """
    violations: list[Violation] = []

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
        if not resolve_checks(manifest, bp):
            violations.append(
                Violation(
                    rule="blueprint_has_checks",
                    severity="error",
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
        if bp.archetype is not None and bp.archetype not in _VALID_ARCHETYPES:
            violations.append(
                Violation(
                    rule="blueprint-archetype-known",
                    severity="warn",
                    message=(
                        f"Blueprint '{bp.name}' declares archetype='{bp.archetype}' "
                        f"which is not a recognised value "
                        f"(known: {sorted(_VALID_ARCHETYPES)})."
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

    return violations


def has_errors(violations: list[Violation]) -> bool:
    """Return True if any violation has severity 'error'."""
    return any(v.severity == "error" for v in violations)


def lint_flow(
    flow: FlowDefinition,
    available_blueprints: set[str],
    available_specialists: set[str] | None = None,
) -> list[Violation]:
    """Run Policy Gate rules specific to a FlowDefinition.

    Rules:
    1. Flow must declare at least one stage              (error) — no Assurance Loop otherwise.
    2. Every blueprint stage's blueprint must exist      (error) — resolvable execution.
    3. Every specialist stage's specialist must exist    (error) — resolvable execution.

    The exactly-one-of blueprint/specialist rule (and verify_only requiring a
    blueprint) is already enforced by the FlowStage pydantic validator at intake.

    Args:
        flow: The FlowDefinition to validate.
        available_blueprints: Set of blueprint names present in the Operator Layer.
        available_specialists: Set of specialist names present in the Operator
            Layer. None is treated as an empty set (no specialists available).

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

    # Rule 2/3: every stage's referenced blueprint or specialist must exist.
    for stage in flow.stages:
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

    return violations


def validate_loop(
    manifest: Manifest, operator_layer: Path, loop_def: LoopDefinition
) -> list[Violation]:
    """Run Policy Gate rules specific to a LoopDefinition.

    The numeric constraints (max_cycles > 0, budget.max > 0, max_consecutive >= 1,
    valid budget unit) are already enforced by the pydantic validators at load
    time, so the only reference this checks is the replenish target: a
    specialist-kind replenish must name a Specialist file that exists.

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

    if replenish is not None and replenish.kind == "flow":
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
