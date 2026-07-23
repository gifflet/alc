# checks.py — `alc checks audit`: re-detect the project's stack(s), compare
# against the Manifest's current check_sets and each Blueprint's resolved
# checks, and PROPOSE upgrades. Pure/read-only: this module never writes —
# proposing is the whole job (roadmap-phase-2.md T13). The CLI (`alc checks
# audit`) prints what this returns; applying a proposal is a manual edit or
# `alc team hire --force`.
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from alc.intake import is_smoke_only
from alc.models import Blueprint, Manifest
from alc.scaffold import _build_check_sets, detect_stacks

# The literal fallback every pack Blueprint keeps so a check_set alone can never
# resolve a Blueprint to zero checks (see packs.py). Shared shape with the Policy
# Gate's advisory rule (policy.py) — kept as a local literal, not a cross-module
# import, since it is a one-line constant, not shared logic.


@dataclass
class CheckSetAudit:
    """One check_set's proposed state.

    ``add`` are checks whose binary is on PATH today but are not yet live in
    the Manifest (new tooling, or a check that was commented out and the
    binary has since been installed). ``unavailable`` are checks still
    missing a binary — informational, so installing the tool later is
    visible as it moving from here into ``add``.
    """

    set_name: str
    is_new: bool                              # True: this set doesn't exist in the Manifest yet
    add: list[tuple[str, list[str]]]
    unavailable: list[tuple[str, list[str]]]


@dataclass
class SmokeOnlyBlueprint:
    """A Blueprint whose resolved checks are nothing but the smoke placeholder,
    even though a stack is detected today — a candidate to wire real checks."""

    blueprint: str
    stacks: list[str]  # detected stack labels, e.g. ["Python"]


@dataclass
class ChecksAudit:
    """Full `alc checks audit` result — a PROPOSAL. Nothing here is written."""

    check_sets: list[CheckSetAudit]
    smoke_only_blueprints: list[SmokeOnlyBlueprint]

    @property
    def has_proposals(self) -> bool:
        return any(cs.is_new or cs.add for cs in self.check_sets) or bool(
            self.smoke_only_blueprints
        )


def audit_checks(
    manifest: Manifest, project_root: Path, blueprints: list[Blueprint]
) -> ChecksAudit:
    """Re-detect stacks and diff them against *manifest*'s check_sets and *blueprints*.

    Args:
        manifest: The loaded Manifest (its check_sets are the baseline).
        project_root: Directory to re-run stack detection against.
        blueprints: Every Blueprint in the Operator Layer (for the smoke-only scan).

    Returns:
        A ChecksAudit — every field is a proposal; nothing is written to disk.
    """
    stacks = detect_stacks(project_root)
    fresh_sets = _build_check_sets(stacks)

    check_sets: list[CheckSetAudit] = []
    for set_name, checks in sorted(fresh_sets.items()):
        live_names = {c.name for c in manifest.check_sets.get(set_name, [])}
        is_new = set_name not in manifest.check_sets
        add: list[tuple[str, list[str]]] = []
        unavailable: list[tuple[str, list[str]]] = []
        for check_name, command in checks:
            if check_name in live_names:
                continue  # already live — nothing to propose
            if shutil.which(command[0]) is not None:
                add.append((check_name, command))
            else:
                unavailable.append((check_name, command))
        if is_new or add or unavailable:
            check_sets.append(
                CheckSetAudit(set_name=set_name, is_new=is_new, add=add, unavailable=unavailable)
            )

    stack_labels = [label for label, _set_name, _checks in stacks]
    smoke_only_blueprints = [
        SmokeOnlyBlueprint(blueprint=bp.name, stacks=stack_labels)
        for bp in blueprints
        if stack_labels and is_smoke_only(manifest, bp)
    ]

    return ChecksAudit(check_sets=check_sets, smoke_only_blueprints=smoke_only_blueprints)
