# onboard.py — the PURE proposal core of the opt-in `alc onboard` feature.
#
# `alc onboard` helps adopt ALC into a project whose stack ALC does not
# recognize by HARVESTING the checks the project already declares (harvest.py)
# and PROPOSING them for the operator to approve. This module is the pure heart
# of that flow: it turns a HarvestReport into an OnboardProposal and renders a
# human-readable preview of what would be written — and it WRITES NOTHING. The
# apply/write step and the CLI live in separate, later layers; keeping this
# module pure means the proposal can be built, diffed, and tested with no disk.
#
# Everything here is phrased as ALC's OWN recommendation — no external person or
# source is ever named, because a harvested check is simply a check ALC now
# recommends adopting.
from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from alc.harvest import HarvestReport
from alc.intake import is_smoke_only, load_manifest
from alc.manifestedit import validate_manifest_text
from alc.models import Blueprint, Manifest
from alc.policy import Violation
from alc.scaffold import render_check_set
from alc.stagepolicy import STAGE_MIX

# The name of the check_set the harvested checks are proposed under. A project
# ALC does not yet recognize adopts its own declared checks as one named set,
# which its smoke-only blueprints then opt into.
_PROJECT_SET = "project"

_EMPTY_HARVEST_NOTE = (
    "no existing check definitions found — add checks manually or try onboarding "
    "with engine assist later"
)


@dataclass(frozen=True)
class ProposedCheck:
    """One check ALC proposes to adopt, ready to render into a check_set entry.

    Mirrors the shape of `harvest.HarvestedCheck` but is the proposal-layer view:
    `origin` records where the proposal came from (currently only "harvest"; a
    future "engine" origin is added in a later wave). Exactly one of `command`
    (a clean argv token list) or `shell` (a string needing a shell) is set.
    """

    name: str
    command: list[str] | None
    shell: str | None
    available: bool
    origin: str            # "harvest" (a future "engine" origin comes later)
    source_path: str | None


@dataclass(frozen=True)
class OnboardProposal:
    """Everything `alc onboard` would do, as data the operator approves first.

    Nothing here has been written: it is a plan, not an act.
    """

    check_sets: dict[str, list[ProposedCheck]]   # primarily {"project": [...]}
    blueprint_opt_ins: dict[str, str]            # blueprint name -> check_set name
    stage: str | None                            # only ever the operator's answer
    team_hints: list[str]                        # stage-mix archetypes not yet hired
    unknowns: list[str]                          # honest gaps


@dataclass(frozen=True)
class ApplyResult:
    """The outcome of `apply` — what was written, OR the violations that blocked it.

    `applied` is True only when the manifest was persisted. `violations` is
    non-empty ONLY on a blocked apply (validate-before-persist failed and
    nothing was written). `notes` carries non-fatal remarks — a "nothing to
    apply" no-op, or a blueprint opt-in that was skipped (missing/odd file)
    without failing the whole apply.
    """

    applied: bool
    sets_added: list[str]            # names of the check_sets appended
    blueprints_opted_in: list[str]   # blueprints given a `check_set:` line
    stage_set: bool                  # whether a `stage:` line was appended
    violations: list[Violation]      # non-empty ONLY when the apply was blocked
    notes: list[str]                 # honest, non-fatal remarks


def build_proposal(
    manifest: Manifest,
    project_root: Path,  # noqa: ARG001 — reserved for a future engine-origin harvest
    blueprints: list[Blueprint],
    harvest_report: HarvestReport,
    stage: str | None = None,
    hired_archetypes: list[str] | None = None,
) -> OnboardProposal:
    """Build the OnboardProposal for a project — PURE, writes nothing.

    Maps the (already de-duplicated) harvested checks into a single "project"
    check_set, proposes a `check_set: project` opt-in for every smoke-only
    blueprint (but only when a "project" set actually exists), passes the
    operator's answered `stage` through untouched (never inferred), derives
    `team_hints` from that stage's target mix, and records honest gaps in
    `unknowns`.

    Args:
        manifest: The project's Manifest — used to resolve each blueprint's
            effective checks (`is_smoke_only`).
        project_root: The project directory. Currently unused (harvest has
            already run); reserved for a future engine-assisted harvest.
        blueprints: The project's blueprints — a smoke-only one is a candidate
            for a `check_set: project` opt-in.
        harvest_report: The deterministic harvest result to adopt.
        stage: The operator's answered product stage, or None. NEVER inferred.
        hired_archetypes: Archetypes already hired, or None (treated as empty).

    Returns:
        An OnboardProposal describing what would be written. Nothing is written.
    """
    unknowns: list[str] = []

    # 1. Harvested checks -> the "project" check_set. Harvest already dedups, so
    #    map through order-preservingly. An empty harvest proposes no set at all.
    proposed = [
        ProposedCheck(
            name=hc.name,
            command=hc.command,
            shell=hc.shell,
            available=hc.available,
            origin="harvest",
            source_path=hc.source_path,
        )
        for hc in harvest_report.checks
    ]
    check_sets: dict[str, list[ProposedCheck]] = {}
    if proposed:
        check_sets[_PROJECT_SET] = proposed
    else:
        unknowns.append(_EMPTY_HARVEST_NOTE)

    # 2. Blueprint opt-ins — only when a "project" set will actually exist (never
    #    opt a blueprint into a set that will not be written). `is_smoke_only`
    #    already exempts `plan`, and a blueprint resolving real checks is skipped.
    blueprint_opt_ins: dict[str, str] = {}
    if _PROJECT_SET in check_sets:
        for bp in blueprints:
            if is_smoke_only(manifest, bp):
                blueprint_opt_ins[bp.name] = _PROJECT_SET

    # 3. Stage is EXACTLY the operator's answer — never inferred from the code or
    #    the manifest. team_hints are this stage's core archetypes not yet hired.
    hired = set(hired_archetypes or [])
    team_hints: list[str] = []
    if stage is not None:
        mix = STAGE_MIX.get(stage)
        if mix is None:
            unknowns.append(
                f"stage '{stage}' has no known archetype mix — no team hints offered"
            )
        else:
            team_hints = [a for a in mix.get("core", []) if a not in hired]

    return OnboardProposal(
        check_sets=check_sets,
        blueprint_opt_ins=blueprint_opt_ins,
        stage=stage,
        team_hints=team_hints,
        unknowns=unknowns,
    )


def _command_tuples(checks: list[ProposedCheck]) -> list[tuple[str, list[str]]]:
    """The (name, command) pairs `render_check_set` renders. Harvested checks are
    argv-form; a shell-only check (a future origin) has no argv and is skipped
    here — it still appears in the summary table below."""
    return [(c.name, c.command) for c in checks if c.command is not None]


def _proposed_manifest(manifest_raw: str, proposal: OnboardProposal) -> str:
    """The manifest text ALC would produce, by APPENDING the proposed additions.

    Pure and non-destructive: the current text is never mutated on disk — this
    just appends the rendered `check_sets` block(s) and the `stage:` line so a
    diff can show exactly what onboarding would add. The real merge is the
    later apply step's job; this is a preview only.
    """
    additions: list[str] = []
    if proposal.check_sets:
        additions.append("check_sets:")
        additions.extend(
            render_check_set(name, _command_tuples(checks))
            for name, checks in proposal.check_sets.items()
        )
    if proposal.stage is not None:
        additions.append(f"stage: {proposal.stage}")
    if not additions:
        return manifest_raw
    return manifest_raw.rstrip("\n") + "\n\n" + "\n".join(additions) + "\n"


def _check_form(check: ProposedCheck) -> str:
    """The command/shell column of the summary table for one proposed check."""
    if check.command is not None:
        return " ".join(check.command)
    return check.shell or ""


def render_preview(
    proposal: OnboardProposal,
    manifest_raw: str,
    blueprints_raw: dict[str, str],
) -> str:
    """Render a human-readable preview of *proposal* — PURE, returns a string.

    Shows, for the operator to approve BEFORE anything is written: the rendered
    `check_sets` block(s); a unified diff of `manifest.yaml` with the appended
    check_sets + `stage:`; a per-blueprint note of the one-line `check_set:`
    opt-in that would be inserted; a summary table of every proposed check; and
    the honest `unknowns` and `team_hints`. Writes nothing.

    Args:
        proposal: The proposal to preview.
        manifest_raw: The current `manifest.yaml` text (used for the diff only —
            never mutated).
        blueprints_raw: {blueprint name -> its current raw text}, used to note
            each opt-in's target.

    Returns:
        The preview as a single string.
    """
    lines: list[str] = ["# alc onboard — proposal preview", ""]

    # Proposed check_sets, rendered with the same off-PATH commenting `alc init`
    # uses (a binary not on PATH is written commented out, never live).
    if proposal.check_sets:
        lines.append("## Proposed check_sets")
        for name, checks in proposal.check_sets.items():
            lines.append("")
            lines.append(render_check_set(name, _command_tuples(checks)))
        lines.append("")

    # A diff of manifest.yaml showing exactly what would be appended.
    lines.append("## manifest.yaml (proposed additions)")
    new_manifest = _proposed_manifest(manifest_raw, proposal)
    diff = difflib.unified_diff(
        manifest_raw.splitlines(),
        new_manifest.splitlines(),
        fromfile="manifest.yaml",
        tofile="manifest.yaml",
        lineterm="",
    )
    lines.extend(diff)
    lines.append("")

    # Per-blueprint opt-in notes.
    if proposal.blueprint_opt_ins:
        lines.append("## Blueprint opt-ins")
        for bp_name, set_name in proposal.blueprint_opt_ins.items():
            note = (
                f"- {bp_name}: add `check_set: {set_name}` to its front-matter "
                "(it currently resolves to the smoke placeholder only)"
            )
            if bp_name not in blueprints_raw:
                note += " [raw blueprint text not supplied]"
            elif "check_set:" in blueprints_raw[bp_name]:
                note += " [a check_set is already declared — review before applying]"
            lines.append(note)
        lines.append("")

    # Summary table of every proposed check.
    lines.append("## Checks")
    lines.append("| check | command / shell | source | status |")
    lines.append("| --- | --- | --- | --- |")
    for checks in proposal.check_sets.values():
        for check in checks:
            status = "available" if check.available else "commented — binary off PATH"
            lines.append(
                f"| {check.name} | {_check_form(check)} | "
                f"{check.source_path or ''} | {status} |"
            )
    lines.append("")

    # Honest notes.
    if proposal.unknowns:
        lines.append("## Notes")
        lines.extend(f"- {note}" for note in proposal.unknowns)
        lines.append("")

    if proposal.team_hints:
        lines.append("## Team hints")
        lines.append(
            f"stage '{proposal.stage}' suggests hiring: "
            f"{', '.join(proposal.team_hints)}"
        )
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# apply — the ONLY writer in the whole onboard flow (append-only,
# validate-before-persist). build_proposal/render_preview above stay pure.
# ---------------------------------------------------------------------------


def _splice_check_sets(raw: str, proposal: OnboardProposal) -> str | None:
    """Append the proposal's check_sets into the manifest's `check_sets:` mapping.

    APPEND-ONLY: existing lines are never mutated. The rendered sets are spliced
    in right after the mapping's last entry, matching its 2-space indentation
    (`render_check_set` already emits that). Returns the new text, or None when
    the `check_sets:` key cannot be located confidently — the caller then FAILS
    SAFELY and writes nothing rather than risk corrupting the file.
    """
    lines = raw.split("\n")

    cs_idx: int | None = None
    for i, line in enumerate(lines):
        if line.rstrip() == "check_sets:":
            cs_idx = i
            break
    if cs_idx is None:
        return None

    # Walk to the end of the mapping body: the last indented (non-blank) line
    # before the next top-level key. Blank lines don't extend the body, so the
    # new sets land right after the last real entry, not after a trailing gap.
    insert_at = cs_idx + 1
    i = cs_idx + 1
    while i < len(lines):
        line = lines[i]
        if line == "":
            i += 1
            continue
        if line[:1] in (" ", "\t"):
            insert_at = i + 1
            i += 1
            continue
        break  # a top-level, non-blank line ends the mapping

    inserted: list[str] = []
    for name, checks in proposal.check_sets.items():
        inserted.append("")  # blank separator between sets, matching `alc init`
        inserted.extend(render_check_set(name, _command_tuples(checks)).split("\n"))

    new_lines = lines[:insert_at] + inserted + lines[insert_at:]
    return "\n".join(new_lines)


def _append_stage(text: str, stage: str) -> str:
    """Append `stage: <stage>` as a new top-level line, preserving everything else."""
    lines = text.split("\n")
    stage_line = f"stage: {stage}"
    if lines and lines[-1] == "":
        # File ends with a newline: keep it by inserting before the trailing "".
        lines.insert(len(lines) - 1, stage_line)
    else:
        lines.append(stage_line)
        lines.append("")
    return "\n".join(lines)


def _opt_in_blueprint(text: str, set_name: str) -> tuple[str | None, str | None]:
    """Splice a single `check_set: <set_name>` line into a blueprint's front-matter.

    Comment-safe and append-only: the line is inserted right after the
    `compute_tier:` line inside the `---` front-matter fences. Returns
    (new_text, None) on success, or (None, reason) when the file is missing the
    front-matter, its compute_tier line, or already declares a check_set — the
    caller then skips it with the reason as a note, never crashing.
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, "no YAML front-matter"

    close: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            close = i
            break
    if close is None:
        return None, "unterminated front-matter"

    fm = range(1, close)
    if any(lines[i].startswith("check_set:") for i in fm):
        return None, "already declares a check_set"

    ct_idx: int | None = None
    for i in fm:
        if lines[i].startswith("compute_tier:"):
            ct_idx = i
            break
    if ct_idx is None:
        return None, "no compute_tier line in front-matter"

    new_lines = lines[: ct_idx + 1] + [f"check_set: {set_name}"] + lines[ct_idx + 1 :]
    return "\n".join(new_lines), None


def _blueprints_dir(operator_layer: Path) -> Path:
    """The project's blueprints directory (falls back to the scaffold default)."""
    try:
        rel = load_manifest(operator_layer).blueprints_dir
    except Exception:  # noqa: BLE001 — a broken manifest still resolves the default dir
        rel = ".alc/blueprints"
    return operator_layer.parent / rel


def apply(proposal: OnboardProposal, operator_layer: Path) -> ApplyResult:
    """Apply *proposal* to *operator_layer* — the ONLY function here that writes.

    Append-only and validate-before-persist:

    1. Build the CANDIDATE manifest by APPENDING the proposed check_sets into the
       `check_sets:` mapping and, when answered, a top-level `stage:` line —
       existing comments and keys survive byte-for-byte.
    2. Validate the candidate through the shared gate
       (`manifestedit.validate_manifest_text`). On any blocking violation, write
       NOTHING and return the violations.
    3. Only on a clean gate: write the candidate manifest, then splice one
       `check_set:` line into each opted-in blueprint. A missing/odd blueprint is
       skipped with a note, never a crash.

    An empty proposal (no sets, no stage, no opt-ins) is a clean no-op.

    Returns:
        An ApplyResult reporting what was written, or the violations that
        blocked the write.
    """
    manifest_path = operator_layer / "manifest.yaml"

    manifest_change = bool(proposal.check_sets) or proposal.stage is not None
    if not manifest_change and not proposal.blueprint_opt_ins:
        return ApplyResult(
            applied=False,
            sets_added=[],
            blueprints_opted_in=[],
            stage_set=False,
            violations=[],
            notes=["nothing to apply"],
        )

    raw = manifest_path.read_text()

    # 1. Build the candidate by appending (never re-dumping).
    candidate = raw
    if proposal.check_sets:
        spliced = _splice_check_sets(candidate, proposal)
        if spliced is None:
            return ApplyResult(
                applied=False,
                sets_added=[],
                blueprints_opted_in=[],
                stage_set=False,
                violations=[
                    Violation(
                        rule="onboard-check-sets-anchor",
                        severity="error",
                        message=(
                            "could not locate the `check_sets:` mapping in "
                            "manifest.yaml — nothing was written"
                        ),
                    )
                ],
                notes=[],
            )
        candidate = spliced
    if proposal.stage is not None:
        candidate = _append_stage(candidate, proposal.stage)

    # 2. Validate-before-persist — a blocked apply writes NOTHING.
    violations = validate_manifest_text(candidate, operator_layer)
    if violations:
        return ApplyResult(
            applied=False,
            sets_added=[],
            blueprints_opted_in=[],
            stage_set=False,
            violations=violations,
            notes=[],
        )

    # 3. Persist the manifest, then opt each blueprint in with a single line.
    manifest_path.write_text(candidate)

    notes: list[str] = []
    blueprints_dir = _blueprints_dir(operator_layer)
    opted_in: list[str] = []
    for bp_name, set_name in proposal.blueprint_opt_ins.items():
        bp_path = blueprints_dir / f"{bp_name}.md"
        if not bp_path.is_file():
            notes.append(f"blueprint '{bp_name}' not found — opt-in skipped")
            continue
        try:
            bp_text = bp_path.read_text()
        except OSError as exc:
            notes.append(f"blueprint '{bp_name}' unreadable ({exc}) — opt-in skipped")
            continue
        new_bp, skip_reason = _opt_in_blueprint(bp_text, set_name)
        if new_bp is None:
            notes.append(f"blueprint '{bp_name}' — opt-in skipped: {skip_reason}")
            continue
        bp_path.write_text(new_bp)
        opted_in.append(bp_name)

    return ApplyResult(
        applied=True,
        sets_added=list(proposal.check_sets.keys()),
        blueprints_opted_in=opted_in,
        stage_set=proposal.stage is not None,
        violations=[],
        notes=notes,
    )
