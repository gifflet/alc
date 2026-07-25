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
from alc.onboard import ApplyResult, apply, build_proposal
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
