# stagepolicy.py — the product stage as control-plane data (roadmap-phase-4.md T5/T6).
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
# T6) and scaffolding. A Blueprint with no `archetype` is NEVER penalised by
# any rule here — that is what keeps the taxonomy from turning into paperwork.
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from alc.models import Blueprint, FlowReport, Manifest
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
       `alc team hire <archetype>`. A missing SECONDARY member never warns
       (it was always optional).
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
                        f"hint: alc team hire {archetype}"
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
class MixHealthReport:
    """`alc team status`'s answer to "is the autonomous work the right work
    for this product's stage?" (roadmap-phase-4.md T6, the essay's central
    question). `stage`/`core`/`secondary` are None/[] when no stage is
    declared: the breakdown is still built, just never judged against a mix.
    `total_runs == 0` means no archived report exists yet — render that as
    "no data yet", never a division by zero or a misleading all-zero table.
    """

    stage: str | None
    core: list[str] = field(default_factory=list)
    secondary: list[str] = field(default_factory=list)
    by_archetype: list[ArchetypeSpend] = field(default_factory=list)
    total_runs: int = 0


def mix_health(done_dir: Path, manifest: Manifest) -> MixHealthReport:
    """Aggregate archived reports (`done_dir/*.report.json`) by `RunReport.archetype`.

    Mirrors `audit.audit_window`'s read pattern: an unreadable or invalid
    archive is skipped, never fatal; a missing/empty `done_dir` yields a
    report with `total_runs == 0` (no data yet, not zeroed statistics for
    archetypes that were never even attempted).
    """
    buckets: dict[str | None, ArchetypeSpend] = {}
    total_runs = 0

    if done_dir.is_dir():
        for report_file in sorted(done_dir.glob("*.report.json")):
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

    return MixHealthReport(
        stage=manifest.stage,
        core=list(mix.get("core", [])) if mix else [],
        secondary=list(mix.get("secondary", [])) if mix else [],
        by_archetype=by_archetype,
        total_runs=total_runs,
    )
