# stagepolicy.py — the product stage as control-plane data (roadmap-phase-4.md T5/T6/T7).
#
# `Manifest.stage` declares which growth stage the product is in (the essay this
# roadmap comes from: pre-pmf / growth / strong-pmf). STAGE_MIX below is the
# DEFAULT target archetype mix per stage — a health HEURISTIC, not a law of
# physics, so it stays plain data with an explicit escape hatch
# (`Manifest.stage_mix`) rather than hardcoded logic with no way out.
#
# Every rule `lint_stage` reports is ADVISORY (warn, or error only for a
# malformed `stage_mix` override itself) — the stage never changes how a
# mandate executes; its authority is limited to warns, reports (`mix_health`,
# T6; `validate_stage_mix`, T7) and scaffolding. A Blueprint with no
# `archetype` — and a Conductor `PlannedUnit` with no determinable one — is
# NEVER penalised by any rule here; that is what keeps the taxonomy from
# turning into paperwork.
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from alc.models import (
    Blueprint,
    ConductorPlan,
    FlowDefinition,
    FlowReport,
    Manifest,
    PlannedUnit,
    Specialist,
)
from alc.policy import VALID_ARCHETYPES, Violation

# `core`: the archetypes the stage's autonomous work should center on (the
# essay's "pré-PMF = prototyper+builder+sweeper", etc). `secondary`: a smaller,
# optional presence (the essay's "+ algum maintainer/builder") — expected, but
# a missing secondary member never warns (see lint_stage rule 2).
STAGE_MIX: dict[str, dict[str, list[str]]] = {
    "pre-pmf": {"core": ["prototyper", "builder", "sweeper"], "secondary": []},
    "growth": {"core": ["builder", "sweeper", "grower"], "secondary": ["maintainer"]},
    "strong-pmf": {"core": ["sweeper", "grower", "maintainer"], "secondary": ["builder"]},
}

_VALID_STAGE_MIX_KEYS: frozenset[str] = frozenset({"core", "secondary"})


def effective_mix(manifest: Manifest) -> dict[str, list[str]] | None:
    """Return {"core": [...], "secondary": [...]} for `manifest.stage`.

    None when no stage is declared — the opt-in invariant that keeps a project
    with no `stage` (every `alc init` layer) free of any mix rule.
    `manifest.stage_mix`, when set, REPLACES the default mix for the declared
    stage wholesale — the operator opted out of the built-in formula on purpose.
    """
    if manifest.stage is None:
        return None
    if manifest.stage_mix is not None:
        return manifest.stage_mix
    return STAGE_MIX[manifest.stage]


def lint_stage(manifest: Manifest, blueprints: list[Blueprint]) -> list[Violation]:
    """Advisory Policy Gate rules for `stage`/`stage_mix` — never blocks a run.

    Rules:
    1. `stage_mix`, when set, uses only the "core"/"secondary" keys and lists
       only recognised archetype names                (error) — a malformed
                                                          override silently
                                                          does nothing, which
                                                          defeats the point of
                                                          declaring it.
    2. A stage's CORE archetype with no Blueprint declaring it   (warn) — hint:
       `alc team hire <archetype>` (additive: adds the pack's missing files) or
       declare `archetype: <archetype>` on an existing Blueprint — truthful for
       the not-hired, partially-hired, AND own-Blueprint cases. A missing
       SECONDARY member never warns (it was always optional).
    3. A `compute_tier: deep` Blueprint whose archetype sits outside the
       stage's mix (core + secondary)                   (warn) — a costly
                                                          tier spent on work
                                                          this stage does not
                                                          prioritise. A
                                                          Blueprint with no
                                                          `archetype` is NEVER
                                                          checked by this rule.

    Rules 2/3 are no-ops when `manifest.stage` is None — nothing to compare
    against, so a freshly `alc init`-ed project (which writes no `stage`)
    stays silent.
    """
    violations: list[Violation] = []

    if manifest.stage_mix is not None:
        unknown_keys = sorted(set(manifest.stage_mix) - _VALID_STAGE_MIX_KEYS)
        if unknown_keys:
            violations.append(
                Violation(
                    rule="stage-mix-shape",
                    severity="error",
                    message=(
                        f"manifest.stage_mix has unknown key(s) {unknown_keys} — "
                        f"only {sorted(_VALID_STAGE_MIX_KEYS)} are recognised."
                    ),
                )
            )
        for group, names in manifest.stage_mix.items():
            for name in names:
                if name not in VALID_ARCHETYPES:
                    violations.append(
                        Violation(
                            rule="stage-mix-archetype-known",
                            severity="error",
                            message=(
                                f"manifest.stage_mix['{group}'] names '{name}', which is "
                                f"not a recognised archetype (known: {sorted(VALID_ARCHETYPES)})."
                            ),
                        )
                    )

    if manifest.stage is None:
        return violations

    mix = effective_mix(manifest)
    assert mix is not None  # manifest.stage is set, so effective_mix never returns None here
    hired = {bp.archetype for bp in blueprints if bp.archetype is not None}

    for archetype in mix.get("core", []):
        if archetype not in hired:
            violations.append(
                Violation(
                    rule="stage-core-archetype-missing",
                    severity="warn",
                    message=(
                        f"Stage '{manifest.stage}' expects a '{archetype}' in the mix, "
                        f"but no Blueprint declares archetype: {archetype} — "
                        f"hint: alc team hire {archetype} (adds the pack's missing file(s)) — "
                        f"or declare `archetype: {archetype}` on an existing Blueprint"
                    ),
                )
            )

    in_mix = set(mix.get("core", [])) | set(mix.get("secondary", []))
    for bp in blueprints:
        if bp.archetype is None:
            continue  # never penalised — that is what keeps this from being paperwork
        if bp.compute_tier == "deep" and bp.archetype not in in_mix:
            violations.append(
                Violation(
                    rule="stage-deep-tier-off-mix",
                    severity="warn",
                    message=(
                        f"Blueprint '{bp.name}' runs at compute_tier: deep with "
                        f"archetype: {bp.archetype}, which is outside stage "
                        f"'{manifest.stage}''s mix ({sorted(in_mix)}) — a costly tier "
                        "spent on work the current stage does not prioritise."
                    ),
                )
            )

    return violations


# ---------------------------------------------------------------------------
# Mix Health (roadmap-phase-4.md T6) — `RunReport.archetype` aggregated over
# the archived reports and compared with the stage's target mix.
# ---------------------------------------------------------------------------


@dataclass
class ArchetypeSpend:
    """Aggregate of every archived RunReport bucketed under one archetype.

    `archetype` is None for reports whose Blueprint set none — shown for
    completeness, but the taxonomy rules never single it out.
    """

    archetype: str | None
    runs: int = 0
    span: int = 0
    cost_usd: float = 0.0
    net_lines: int = 0  # sum(adds - dels) across every stage that had a diffstat


@dataclass
class IdleCoreArchetype:
    """A stage CORE archetype with ZERO archived runs, plus the ONE actionable
    hint for it — carried IN the report so the CLI and the UI render the same
    guidance from one computation, never each re-deriving it (the bug that let
    the CLI hint "hire X" for an archetype already on the team).

    `hired` and `hint` are derived from the roster passed to `mix_health`
    (hired-archetype -> its loop names): not hired -> hire it; hired WITH a loop
    -> run that loop; hired with NO loop -> route a demand through its
    blueprints. Reporting only, the same zero-runtime-effect contract as
    `Blueprint.archetype`.
    """

    archetype: str
    hired: bool
    hint: str


@dataclass
class MixHealthReport:
    """`alc team status`'s answer to "is the autonomous work the right work
    for this product's stage?" (roadmap-phase-4.md T6, the essay's central
    question). `stage`/`core`/`secondary` are None/[] when no stage is
    declared: the breakdown is still built, just never judged against a mix.
    `total_runs == 0` means no archived report exists yet — render that as
    "no data yet", never a division by zero or a misleading all-zero table.
    `idle_core` names the core archetypes with no runs and the right hint for
    each (see IdleCoreArchetype); empty when no stage is declared. Additive
    default keeps every existing consumer identical.
    """

    stage: str | None
    core: list[str] = field(default_factory=list)
    secondary: list[str] = field(default_factory=list)
    by_archetype: list[ArchetypeSpend] = field(default_factory=list)
    total_runs: int = 0
    idle_core: list[IdleCoreArchetype] = field(default_factory=list)


MIX_HEALTH_WINDOW_S: float = 30 * 86400
"""Default trailing window for Mix Health — the archetype MIX is a picture of RECENT
work, not all-time history, and bounding it keeps the aggregation from parsing every
report a long-lived project ever accumulated (the `runs/` + `done/` scan is O(n))."""


def mix_health(
    done_dir: Path,
    manifest: Manifest,
    roster: Mapping[str, Sequence[str]] | None = None,
    extra_report_dir: Path | None = None,
    since_epoch: float | None = None,
) -> MixHealthReport:
    """Aggregate archived reports (`*.report.json`) by `RunReport.archetype`.

    Reads the queue's `done/` reports and, when *extra_report_dir* is given, the
    `runs/` reports a direct `alc run` archives there — so a landed interactive run
    (e.g. `alc run refactor`, archetype: sweeper) counts, instead of reading as
    "sweeper never exercised" when only `alc tick` work was tracked. When
    *since_epoch* is given, a report whose archive-file mtime is older is skipped —
    Mix Health reflects the RECENT mix and a long-lived project's ancient reports are
    not parsed every load (production callers pass a trailing window; tests and legacy
    callers omit it for all-time). Mirrors `audit.audit_window`'s read pattern: an
    unreadable or invalid archive is skipped, never fatal; absent dirs contribute
    nothing (so `total_runs == 0` means no data yet, not zeroed stats for archetypes
    never attempted).

    ``roster`` maps each hired archetype to the loop names its pack brought; it
    is what turns a bare "core X never ran" into the correct hint (hire it /
    run its loop / route a demand). ``roster=None`` (legacy callers, tests)
    means membership is UNKNOWN -> every idle core is treated as not hired,
    byte-identical to the pre-roster "alc team hire X" behavior.
    """
    buckets: dict[str | None, ArchetypeSpend] = {}
    total_runs = 0

    report_dirs = [done_dir] + ([extra_report_dir] if extra_report_dir is not None else [])
    report_files = sorted(
        f for d in report_dirs if d.is_dir() for f in d.glob("*.report.json")
    )
    for report_file in report_files:
        if since_epoch is not None and report_file.stat().st_mtime < since_epoch:
            continue
        try:
            report = FlowReport.model_validate_json(report_file.read_text())
        except (ValidationError, OSError):
            continue

        for stage in report.stages:
            bucket = buckets.setdefault(
                stage.archetype, ArchetypeSpend(archetype=stage.archetype)
            )
            bucket.runs += 1
            bucket.span += stage.scorecard.span
            if stage.usage is not None and stage.usage.cost_usd is not None:
                bucket.cost_usd += stage.usage.cost_usd
            if stage.diffstat is not None:
                bucket.net_lines += stage.diffstat.adds - stage.diffstat.dels
            total_runs += 1

    mix = effective_mix(manifest)
    by_archetype = sorted(buckets.values(), key=lambda b: (-b.runs, b.archetype or ""))

    idle_core: list[IdleCoreArchetype] = []
    for archetype in (mix.get("core", []) if mix else []):
        if archetype in buckets:
            continue  # it was exercised — never idle
        if roster is not None and archetype in roster:
            loops = roster[archetype]
            if loops:
                hint = f"run its loop (alc loop {loops[0]})"
            else:
                hint = (
                    'route a demand through its blueprints '
                    '(alc conduct "<goal>" or alc enqueue <flow> "<task>")'
                )
            idle_core.append(IdleCoreArchetype(archetype=archetype, hired=True, hint=hint))
        else:
            idle_core.append(
                IdleCoreArchetype(
                    archetype=archetype, hired=False, hint=f"alc team hire {archetype}"
                )
            )

    return MixHealthReport(
        stage=manifest.stage,
        core=list(mix.get("core", [])) if mix else [],
        secondary=list(mix.get("secondary", [])) if mix else [],
        by_archetype=by_archetype,
        total_runs=total_runs,
        idle_core=idle_core,
    )


# ---------------------------------------------------------------------------
# Conductor stage-awareness (roadmap-phase-4.md T7) — TWO parts with DIFFERENT
# guarantees:
#   (a) `stage_briefing` — a PROSE nudge folded into the Conductor's planning
#       directive. Probabilistic: the planning model may weigh it, may ignore
#       it entirely. Nothing here enforces anything.
#   (b) `validate_stage_mix` — plain code that runs AFTER the plan already
#       came back, comparing it against the stage's mix. This is the actual
#       guarantee: deterministic, never dependent on the model having
#       cooperated with (a).
# `--strict-stage` (conduct.py) turns (b)'s warnings into a refusal; (a) has no
# equivalent knob because a prompt cannot be "enforced" — only its downstream
# effect (the plan) can be checked, which is exactly what (b) does.
# ---------------------------------------------------------------------------


def stage_briefing(manifest: Manifest) -> str | None:
    """Return prose describing `manifest.stage`'s target mix, or None (T7a).

    Appended to the Conductor's planning directive (see ``conduct.plan_flows``)
    so a planning model WITH the stage in view can weigh it — but this is a
    NUDGE, not a guarantee: the model may still return a plan that ignores it
    entirely. `validate_stage_mix` below is what actually enforces anything.

    None when `manifest.stage` is unset — the opt-in invariant: a project with
    no declared stage gets a byte-identical directive, exactly as before this
    existed.
    """
    mix = effective_mix(manifest)
    if mix is None:
        return None
    core = ", ".join(mix.get("core", [])) or "(none)"
    secondary = ", ".join(mix.get("secondary", [])) or "(none)"
    return (
        "\n\n## Stage\n\n"
        f"This product is at stage '{manifest.stage}'. Its target archetype mix is "
        f"core: {core}; secondary: {secondary}. When it fits the goal, PREFER "
        "targets whose archetype belongs to this mix — a preference, not a hard "
        "rule; ALC checks the plan you return against this mix afterward and may "
        "warn (or, under --strict-stage, refuse) when it drifts, but which targets "
        "best serve the goal is still your call."
    )


def _flow_archetype(
    flow: FlowDefinition,
    blueprints: dict[str, Blueprint],
    specialists: dict[str, Specialist],
) -> str | None:
    """A Flow's archetype, when every blueprint-backed stage AGREES on one.

    A Flow has no archetype of its own — it is a per-STAGE concept (mix_health
    buckets `RunReport.archetype` per ``report.stages[i]``, not per flow). This
    reconstructs a flow-level signal ONLY when it is unambiguous: every stage
    resolves (directly, or via a specialist stage's own Blueprint) to a
    Blueprint that declares the SAME archetype. A stage with no resolvable
    Blueprint, a Blueprint with no archetype, or stages that disagree, all
    fall back to None (unclassified) — a guessed signal would be worse than
    none, and an unclassified unit is never penalised.
    """
    seen: set[str] = set()
    for stage in flow.stages:
        bp_name = stage.blueprint
        if bp_name is None and stage.specialist is not None:
            specialist = specialists.get(stage.specialist)
            bp_name = specialist.blueprint if specialist is not None else None
        bp = blueprints.get(bp_name) if bp_name is not None else None
        if bp is None or bp.archetype is None:
            return None
        seen.add(bp.archetype)
    return seen.pop() if len(seen) == 1 else None


def unit_archetype(
    item: PlannedUnit,
    flows: dict[str, FlowDefinition],
    specialists: dict[str, Specialist],
    blueprints: dict[str, Blueprint],
) -> str | None:
    """Best-effort archetype for one Conductor `PlannedUnit`; None = unclassified.

    A `PlannedUnit` names a Flow or a Specialist, NEVER a Blueprint directly, so
    its archetype takes one extra hop to resolve:
      - ``specialist``: the archetype of the Blueprint its Act step runs.
      - ``flow``: the archetype every blueprint-backed stage agrees on — see
        `_flow_archetype`; ambiguous or unresolvable -> None.

    None is also returned when *item* names something absent from the supplied
    catalog dicts (should not happen — a plan is validated against the same
    catalog it was parsed against — but a stale catalog must degrade to
    "unclassified", never a crash or a false accusation).
    """
    if item.kind == "specialist":
        specialist = specialists.get(item.name)
        if specialist is None:
            return None
        bp = blueprints.get(specialist.blueprint)
        return bp.archetype if bp is not None else None

    flow = flows.get(item.name)
    if flow is None:
        return None
    return _flow_archetype(flow, blueprints, specialists)


def validate_stage_mix(
    manifest: Manifest,
    plan: ConductorPlan,
    flows: dict[str, FlowDefinition],
    specialists: dict[str, Specialist],
    blueprints: dict[str, Blueprint],
) -> list[Violation]:
    """The DETERMINISTIC guarantee behind Conductor stage-awareness (T7b).

    Unlike `stage_briefing` (a prose nudge the planner may ignore), this runs
    in plain code AFTER the plan has already come back — and it is what the
    product actually promises: every `PlannedUnit` whose archetype CAN be
    determined (`unit_archetype`) is checked against `manifest.stage`'s
    effective mix (core + secondary); one that falls outside it gets a
    ``stage-plan-off-mix`` warn. A unit with no determinable archetype is
    NEVER penalised — the same invariant `lint_stage` holds for a Blueprint
    with no `archetype`.

    [] immediately when `manifest.stage` is None — the opt-in invariant: a
    Conductor plan is validated exactly as before this existed.
    """
    if manifest.stage is None:
        return []
    mix = effective_mix(manifest)
    assert mix is not None  # manifest.stage is set, so effective_mix never returns None here
    in_mix = set(mix.get("core", [])) | set(mix.get("secondary", []))

    violations: list[Violation] = []
    for item in plan.items:
        archetype = unit_archetype(item, flows, specialists, blueprints)
        if archetype is None or archetype in in_mix:
            continue
        violations.append(
            Violation(
                rule="stage-plan-off-mix",
                severity="warn",
                message=(
                    f"Planned unit '{item.name}' ({item.kind}) has archetype "
                    f"'{archetype}', which falls outside stage '{manifest.stage}''s "
                    f"mix ({sorted(in_mix)})."
                ),
            )
        )
    return violations
