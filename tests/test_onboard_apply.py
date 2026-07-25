# test_onboard_apply.py — Tests for `onboard.apply`, the ONE function of the
# `alc onboard` flow that writes.
#
# apply is append-only and validate-before-persist: it splices the proposal's
# check_sets into `manifest.yaml`, appends the answered `stage:`, validates the
# candidate through the shared gate, and only then writes — followed by a
# single-line `check_set:` opt-in spliced into each named blueprint. These tests
# scaffold a REAL `.alc/` and assert against the reloaded models and the raw
# bytes on disk.
from __future__ import annotations

from pathlib import Path

from alc.harvest import HarvestedCheck, HarvestReport
from alc.intake import load_all_blueprints, load_blueprint, load_manifest
from alc.onboard import ApplyResult, OnboardProposal, ProposedCheck, apply, build_proposal
from alc.scaffold import scaffold


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _scaffolded(tmp_path: Path) -> Path:
    """Scaffold a real `.alc/` under tmp_path and return its operator layer."""
    scaffold(tmp_path)
    return tmp_path / ".alc"


def _harvested(name: str, command: list[str]) -> HarvestedCheck:
    return HarvestedCheck(
        name=name,
        command=command,
        shell=None,
        source="package-json",
        source_path="package.json",
        confidence="high",
        available=True,
    )


def _report(checks: list[HarvestedCheck]) -> HarvestReport:
    return HarvestReport(checks=checks, scanned=[], skipped=[])


def _is_subsequence(original: list[str], produced: list[str]) -> bool:
    """True when every line of *original* appears in *produced* in the same
    order — i.e. apply only INSERTED lines, never removed or reordered any."""
    it = iter(produced)
    return all(line in it for line in original)


# ---------------------------------------------------------------------------
# A full, clean apply
# ---------------------------------------------------------------------------


class TestApplyWritesProposal:
    def test_apply_adds_set_opts_in_blueprint_and_sets_stage(self, tmp_path: Path) -> None:
        ol = _scaffolded(tmp_path)
        manifest = load_manifest(ol)
        blueprints = load_all_blueprints(manifest, ol)
        report = _report([_harvested("test", ["npm", "test"])])
        proposal = build_proposal(manifest, tmp_path, blueprints, report, stage="growth")

        result = apply(proposal, ol)

        assert isinstance(result, ApplyResult)
        assert result.applied is True
        assert result.violations == []
        assert "project" in result.sets_added
        assert "chore" in result.blueprints_opted_in
        assert result.stage_set is True

        # Reload from disk with the REAL loaders — the write is conformant.
        reloaded = load_manifest(ol)
        assert "project" in reloaded.check_sets
        assert reloaded.stage == "growth"

        chore = load_blueprint(ol / "blueprints", "chore")
        assert chore.check_set == "project"

        # The harvested command survives into the rendered set.
        new_text = (ol / "manifest.yaml").read_text()
        assert '["npm", "test"]' in new_text

    def test_pre_existing_lines_and_comments_survive_byte_for_byte(
        self, tmp_path: Path
    ) -> None:
        ol = _scaffolded(tmp_path)
        manifest = load_manifest(ol)
        blueprints = load_all_blueprints(manifest, ol)
        report = _report([_harvested("test", ["npm", "test"])])
        proposal = build_proposal(manifest, tmp_path, blueprints, report, stage="growth")

        before = (ol / "manifest.yaml").read_text()
        apply(proposal, ol)
        after = (ol / "manifest.yaml").read_text()

        # Every original line is still present, in order (apply only inserted).
        assert _is_subsequence(before.split("\n"), after.split("\n"))
        # The scaffold's guiding comments are untouched.
        assert "# Behavioral knobs" in after
        assert "# Reusable named check sets" in after


# ---------------------------------------------------------------------------
# Validate-before-persist — a blocked apply writes NOTHING
# ---------------------------------------------------------------------------


class TestApplyBlockedWritesNothing:
    def test_invalid_manifest_returns_violations_and_leaves_disk_unchanged(
        self, tmp_path: Path
    ) -> None:
        ol = _scaffolded(tmp_path)
        manifest = load_manifest(ol)
        blueprints = load_all_blueprints(manifest, ol)
        report = _report([_harvested("test", ["npm", "test"])])
        # "made-up" is not a recognised stage — the candidate fails to parse, so
        # the whole apply is blocked before anything is written.
        proposal = build_proposal(manifest, tmp_path, blueprints, report, stage="made-up")

        manifest_before = (ol / "manifest.yaml").read_text()
        chore_before = (ol / "blueprints" / "chore.md").read_text()
        result = apply(proposal, ol)

        assert result.applied is False
        assert result.violations  # the blocking violations are surfaced
        assert result.sets_added == []
        assert result.blueprints_opted_in == []
        # Nothing on disk moved — not the manifest, not the blueprints.
        assert (ol / "manifest.yaml").read_text() == manifest_before
        assert (ol / "blueprints" / "chore.md").read_text() == chore_before


# ---------------------------------------------------------------------------
# Empty proposal — a clean no-op
# ---------------------------------------------------------------------------


class TestApplyEmptyProposal:
    def test_empty_proposal_is_a_noop_with_a_clear_result(self, tmp_path: Path) -> None:
        ol = _scaffolded(tmp_path)
        manifest = load_manifest(ol)
        proposal = build_proposal(manifest, tmp_path, [], _report([]))

        before = (ol / "manifest.yaml").read_text()
        result = apply(proposal, ol)

        assert result.applied is False
        assert result.violations == []
        assert result.sets_added == []
        assert result.blueprints_opted_in == []
        assert result.stage_set is False
        assert result.notes  # a clear "nothing to apply" note
        assert (ol / "manifest.yaml").read_text() == before


# ---------------------------------------------------------------------------
# Idempotency — a second apply must never duplicate a set or a stage line
# ---------------------------------------------------------------------------


class TestApplyIsIdempotent:
    def test_rebuilt_proposal_re_applied_writes_nothing_new(self, tmp_path: Path) -> None:
        # The real re-adopt path: the server REBUILDS the proposal from the (now
        # onboarded) manifest, so build_proposal suppresses the live "project"
        # set. Applying that rebuilt proposal a second time must be a clean no-op.
        ol = _scaffolded(tmp_path)
        manifest = load_manifest(ol)
        blueprints = load_all_blueprints(manifest, ol)
        report = _report([_harvested("test", ["npm", "test"])])

        first = build_proposal(manifest, tmp_path, blueprints, report, stage="growth")
        assert apply(first, ol).applied is True
        after_first = (ol / "manifest.yaml").read_text()

        manifest2 = load_manifest(ol)
        blueprints2 = load_all_blueprints(manifest2, ol)
        second_proposal = build_proposal(
            manifest2, tmp_path, blueprints2, report, stage="growth"
        )

        result = apply(second_proposal, ol)

        assert result.applied is False
        assert result.violations == []
        assert result.sets_added == []
        assert result.stage_set is False
        assert result.blueprints_opted_in == []
        # The file did not move a single byte, and exactly ONE of each survives.
        after_second = (ol / "manifest.yaml").read_text()
        assert after_second == after_first
        assert after_second.split("\n").count("  project:") == 1
        assert after_second.split("\n").count("stage: growth") == 1

    def test_stale_proposal_still_carrying_project_is_defensively_skipped(
        self, tmp_path: Path
    ) -> None:
        # A STALE proposal — built BEFORE the first apply, so it still carries the
        # "project" set AND the "growth" stage — is re-applied verbatim. apply must
        # DEFENSIVELY skip both (never trusting a proposal to be fresh) and note it.
        ol = _scaffolded(tmp_path)
        manifest = load_manifest(ol)
        blueprints = load_all_blueprints(manifest, ol)
        report = _report([_harvested("test", ["npm", "test"])])
        stale = build_proposal(manifest, tmp_path, blueprints, report, stage="growth")

        assert apply(stale, ol).applied is True
        after_first = (ol / "manifest.yaml").read_text()
        assert "project" in stale.check_sets  # the proposal really is stale

        result = apply(stale, ol)

        assert result.applied is False
        assert result.sets_added == []
        assert result.stage_set is False
        after_second = (ol / "manifest.yaml").read_text()
        assert after_second == after_first
        assert after_second.split("\n").count("  project:") == 1
        assert after_second.split("\n").count("stage: growth") == 1
        # Each defensive skip is explained honestly.
        assert any("already present" in n for n in result.notes)
        assert any("stage already set" in n for n in result.notes)

    def test_second_apply_of_a_new_set_alongside_an_existing_one(
        self, tmp_path: Path
    ) -> None:
        # A proposal whose "project" set already lives in the manifest but which
        # ALSO carries a genuinely new set: only the new set is spliced, the live
        # one is skipped — no duplicate "project:" block.
        ol = _scaffolded(tmp_path)
        manifest = load_manifest(ol)
        report = _report([_harvested("test", ["npm", "test"])])
        apply(build_proposal(manifest, tmp_path, [], report), ol)

        mixed = OnboardProposal(
            check_sets={
                "project": [
                    ProposedCheck(
                        name="test",
                        command=["npm", "test"],
                        shell=None,
                        available=True,
                        origin="harvest",
                        source_path="package.json",
                    )
                ],
                "extra": [
                    ProposedCheck(
                        name="lint",
                        command=["true"],
                        shell=None,
                        available=True,
                        origin="harvest",
                        source_path="package.json",
                    )
                ],
            },
            blueprint_opt_ins={},
            stage=None,
            team_hints=[],
            unknowns=[],
        )

        result = apply(mixed, ol)

        assert result.applied is True
        assert result.sets_added == ["extra"]
        text = (ol / "manifest.yaml").read_text()
        assert text.split("\n").count("  project:") == 1
        assert text.split("\n").count("  extra:") == 1
