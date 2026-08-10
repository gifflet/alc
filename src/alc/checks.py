# checks.py — `alc checks audit` and `alc checks history`: two read-only
# `alc checks` actions.
#
# `audit` re-detects the project's stack(s), compares against the Manifest's
# current check_sets and each Blueprint's resolved checks, and PROPOSES
# upgrades (roadmap-phase-2.md T13).
#
# `history` aggregates the run logs' `check_finished` events (roadmap-phase-3.md
# T10) into per-check pass-rate, mean duration, and a flake score — the data
# `flaky: N` (T11) and a quarantine decision are read against.
#
# Both are pure/read-only: neither ever writes — proposing/reporting is the
# whole job. The CLI (`alc checks <action>`) prints what these return; applying
# an audit proposal is a manual edit or `alc team hire --force`.
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from alc.intake import is_smoke_only
from alc.models import Blueprint, Manifest
from alc.pydeps import unavailable_hint
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

    ``install_hints`` (check name -> hint) annotates the ``unavailable``
    entries the PROJECT itself can satisfy — a tool pyproject.toml declares,
    or an env-manager runner (`uv run ...`) whose manager is off PATH — so
    "declared but not installed" reads differently from "not a tool this
    project uses" (which gets no entry).
    """

    set_name: str
    is_new: bool                              # True: this set doesn't exist in the Manifest yet
    add: list[tuple[str, list[str]]]
    unavailable: list[tuple[str, list[str]]]
    install_hints: dict[str, str] = field(default_factory=dict)


@dataclass
class SmokeOnlyBlueprint:
    """A Blueprint whose resolved checks are nothing but the smoke placeholder —
    a candidate to wire real checks. Always reported, whether or not a stack was
    detected: ``stacks`` are the detected stack labels, and ``stacks == []`` means
    NO stack was detected (the case that needs real checks the most)."""

    blueprint: str
    stacks: list[str]  # detected stack labels, e.g. ["Python"]; [] when none detected


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
    fresh_sets = _build_check_sets(stacks, project_root)

    check_sets: list[CheckSetAudit] = []
    for set_name, checks in sorted(fresh_sets.items()):
        live_names = {c.name for c in manifest.check_sets.get(set_name, [])}
        is_new = set_name not in manifest.check_sets
        add: list[tuple[str, list[str]]] = []
        unavailable: list[tuple[str, list[str]]] = []
        install_hints: dict[str, str] = {}
        for check_name, command in checks:
            if check_name in live_names:
                continue  # already live — nothing to propose
            if shutil.which(command[0]) is not None:
                add.append((check_name, command))
            else:
                unavailable.append((check_name, command))
                hint = unavailable_hint(project_root, command)
                if hint is not None:
                    install_hints[check_name] = hint
        if is_new or add or unavailable:
            check_sets.append(
                CheckSetAudit(
                    set_name=set_name,
                    is_new=is_new,
                    add=add,
                    unavailable=unavailable,
                    install_hints=install_hints,
                )
            )

    # A smoke-only Blueprint is ALWAYS reported — a stackless project (stacks == [])
    # is exactly where the "no real checks" gap is most dangerous, so it must not be
    # silenced. `plan` stays exempt via is_smoke_only().
    stack_labels = [label for label, _set_name, _checks in stacks]
    smoke_only_blueprints = [
        SmokeOnlyBlueprint(blueprint=bp.name, stacks=stack_labels)
        for bp in blueprints
        if is_smoke_only(manifest, bp)
    ]

    return ChecksAudit(check_sets=check_sets, smoke_only_blueprints=smoke_only_blueprints)


# ---------------------------------------------------------------------------
# `alc checks history` (roadmap-phase-3.md T10)
# ---------------------------------------------------------------------------


@dataclass
class CheckHistory:
    """Aggregate history for one check, computed from every ``check_finished``
    event across the run logs.

    ``flake_score`` is the fraction of consecutive pass/fail TRANSITIONS in
    chronological order — 0.0 means the outcome never flips (whether it always
    passes or is simply always broken), 1.0 means it flips on every single run.
    Only alternating outcomes raise it, so a check that is consistently broken
    is not conflated with one that is actually flaky.
    """

    name: str
    runs: int
    passes: int
    pass_rate: float
    mean_duration_s: float
    flake_score: float


def _iter_check_finished(runs_dir: Path):
    """Yield every well-formed ``check_finished`` event under *runs_dir*.

    Chronological order: run-log files are named ``<UTCts>-...`` (see
    ``events.new_run_log_path``), so sorting by filename sorts by time; within
    one file, events are already in the order they were appended. Best-effort:
    an unreadable file, a malformed JSON line, or an event missing the fields
    this needs is skipped rather than aborting the whole aggregation.
    """
    if not runs_dir.is_dir():
        return
    for log_file in sorted(runs_dir.glob("*.jsonl")):
        try:
            lines = log_file.read_text().splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                event.get("event") != "check_finished"
                or not isinstance(event.get("name"), str)
                or not isinstance(event.get("passed"), bool)
            ):
                continue
            yield event


def check_history(runs_dir: Path) -> list[CheckHistory]:
    """Aggregate every ``check_finished`` event under *runs_dir*, per check name.

    ``duration_s`` is additive (roadmap-phase-3.md T9): an event from an OLDER
    run log that lacks it is still counted for pass-rate/flake-score, just
    excluded from the mean-duration average.

    Returns one CheckHistory per check name that appeared at least once,
    sorted by name. An absent or empty runs_dir yields an empty list.
    """
    passed_by_name: dict[str, list[bool]] = {}
    durations_by_name: dict[str, list[float]] = {}

    for event in _iter_check_finished(runs_dir):
        name = event["name"]
        passed_by_name.setdefault(name, []).append(event["passed"])
        duration = event.get("duration_s")
        if isinstance(duration, int | float):
            durations_by_name.setdefault(name, []).append(float(duration))

    history: list[CheckHistory] = []
    for name in sorted(passed_by_name):
        outcomes = passed_by_name[name]
        runs = len(outcomes)
        passes = sum(1 for p in outcomes if p)
        transitions = sum(1 for a, b in zip(outcomes, outcomes[1:], strict=False) if a != b)
        durations = durations_by_name.get(name, [])
        history.append(
            CheckHistory(
                name=name,
                runs=runs,
                passes=passes,
                pass_rate=passes / runs,
                mean_duration_s=(sum(durations) / len(durations)) if durations else 0.0,
                flake_score=(transitions / (runs - 1)) if runs > 1 else 0.0,
            )
        )
    return history
