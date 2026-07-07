# policy.py — Policy Gate: conformance rules for the Operator Layer.
# Lints a Manifest + its Blueprints and returns Violations with severity error/warn.
# An error violation blocks alc run; a warn is advisory only.
from __future__ import annotations

from dataclasses import dataclass

from alc.intake import resolve_checks
from alc.models import Blueprint, FlowDefinition, Manifest


@dataclass
class Violation:
    """A single Policy Gate finding."""

    rule: str
    severity: str   # "error" or "warn"
    message: str


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

    Resolved checks = the named check_set's checks (if any) plus the Blueprint's own,
    so a Blueprint that only references a check_set still satisfies rule 1.
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

    return violations


def has_errors(violations: list[Violation]) -> bool:
    """Return True if any violation has severity 'error'."""
    return any(v.severity == "error" for v in violations)


def lint_flow(flow: FlowDefinition, available_blueprints: set[str]) -> list[Violation]:
    """Run Policy Gate rules specific to a FlowDefinition.

    Rules:
    1. Flow must declare at least one stage             (error) — no Assurance Loop otherwise.
    2. Every stage's blueprint must exist in the layer  (error) — resolvable execution.

    Args:
        flow: The FlowDefinition to validate.
        available_blueprints: Set of blueprint names present in the Operator Layer.

    Returns:
        List of Violations (may be empty).
    """
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
        return violations  # no point checking stage blueprints if there are none

    # Rule 2: every stage's blueprint must be available.
    for stage in flow.stages:
        if stage.blueprint not in available_blueprints:
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

    return violations
