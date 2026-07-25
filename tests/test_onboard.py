# test_onboard.py — Hermetic tests for the PURE proposal core of `alc onboard`
# (onboard.py): turning a HarvestReport into an OnboardProposal and rendering a
# human-readable preview. Nothing here writes to disk — build_proposal and
# render_preview are pure — so every assertion is against a returned value.
from __future__ import annotations

from pathlib import Path

import pytest

from alc.harvest import HarvestedCheck, HarvestReport
from alc.models import Blueprint, Check, Manifest
from alc.onboard import (
    OnboardProposal,
    ProposedCheck,
    build_proposal,
    render_preview,
)


# ---------------------------------------------------------------------------
# Small builders — keep each test focused on the one thing it asserts.
# ---------------------------------------------------------------------------


def _manifest(stage: str | None = None) -> Manifest:
    return Manifest(
        default_engine="mock",
        compute_tiers={"standard": {"mock": "mock-small"}},
        engines={"mock": {"type": "mock"}},
        stage=stage,
    )


def _manifest_with_project() -> Manifest:
    """A manifest that has ALREADY adopted a "project" check_set — the state a
    prior `alc onboard` apply leaves behind, and the trigger for idempotency."""
    return Manifest(
        default_engine="mock",
        compute_tiers={"standard": {"mock": "mock-small"}},
        engines={"mock": {"type": "mock"}},
        check_sets={"project": [Check(name="test", command=["npm", "run", "test"])]},
    )


def _blueprint(name: str, checks: list[Check]) -> Blueprint:
    return Blueprint(name=name, purpose="x", workflow="w", checks=checks)


_SMOKE = Check(name="smoke", command=["true"])


def _harvested(
    name: str,
    command: list[str],
    *,
    available: bool = True,
    source: str = "package-json",
    source_path: str = "package.json",
) -> HarvestedCheck:
    return HarvestedCheck(
        name=name,
        command=command,
        shell=None,
        source=source,
        source_path=source_path,
        confidence="high",
        available=available,
    )


def _report(checks: list[HarvestedCheck]) -> HarvestReport:
    return HarvestReport(checks=checks, scanned=[], skipped=[])


# ---------------------------------------------------------------------------
# build_proposal — harvest -> check_sets["project"]
# ---------------------------------------------------------------------------


class TestBuildProposalChecks:
    def test_harvest_maps_into_project_set_with_origin_harvest(self) -> None:
        report = _report(
            [
                _harvested("test", ["npm", "run", "test"]),
                _harvested("lint", ["npm", "run", "lint"], available=False),
            ]
        )

        proposal = build_proposal(_manifest(), Path("/x"), [], report)

        assert isinstance(proposal, OnboardProposal)
        project = proposal.check_sets["project"]
        assert [c.name for c in project] == ["test", "lint"]
        assert all(isinstance(c, ProposedCheck) for c in project)
        assert all(c.origin == "harvest" for c in project)
        assert project[0].command == ["npm", "run", "test"]
        assert project[0].source_path == "package.json"
        assert project[0].available is True
        assert project[1].available is False

    def test_empty_harvest_has_no_project_set_and_explains(self) -> None:
        proposal = build_proposal(_manifest(), Path("/x"), [], _report([]))

        assert "project" not in proposal.check_sets
        assert proposal.unknowns  # a clear note is present
        assert any("no existing check" in note.lower() for note in proposal.unknowns)

    def test_already_adopted_project_set_is_suppressed_with_a_distinct_note(
        self,
    ) -> None:
        # Onboarding is IDEMPOTENT: when the manifest already declares a "project"
        # check_set, re-proposing it would duplicate the block on a second adopt.
        # The proposal must leave "project" out and say WHY — with a note DISTINCT
        # from the empty-harvest one, so a reader tells "already onboarded" apart
        # from "nothing harvested".
        adopted = _manifest_with_project()
        report = _report([_harvested("test", ["npm", "run", "test"])])

        proposal = build_proposal(adopted, Path("/x"), [], report)

        assert "project" not in proposal.check_sets
        assert any("already exist" in note.lower() for note in proposal.unknowns)
        # NOT the empty-harvest note — the two reasons stay distinguishable.
        assert not any("no existing check" in note.lower() for note in proposal.unknowns)

    def test_already_adopted_proposes_no_new_opt_ins(self) -> None:
        # With the "project" set suppressed there is no set to opt a blueprint
        # into, so no opt-in is proposed (the first adopt already wired them).
        adopted = _manifest_with_project()
        blueprints = [_blueprint("chore", [_SMOKE])]
        report = _report([_harvested("test", ["npm", "run", "test"])])

        proposal = build_proposal(adopted, Path("/x"), blueprints, report)

        assert proposal.blueprint_opt_ins == {}


# ---------------------------------------------------------------------------
# build_proposal — blueprint opt-ins for smoke-only blueprints
# ---------------------------------------------------------------------------


class TestBuildProposalOptIns:
    def test_smoke_only_blueprints_opt_into_project(self) -> None:
        blueprints = [
            _blueprint("chore", [_SMOKE]),          # smoke-only -> proposed
            _blueprint("plan", [_SMOKE]),           # exempt -> never proposed
            _blueprint("feature", [Check(name="test", command=["pytest"])]),  # real
        ]
        report = _report([_harvested("test", ["npm", "run", "test"])])

        opt_ins = build_proposal(_manifest(), Path("/x"), blueprints, report).blueprint_opt_ins

        assert opt_ins == {"chore": "project"}

    def test_no_opt_ins_when_no_project_set_exists(self) -> None:
        # A smoke-only blueprint but an EMPTY harvest: there is no "project" set to
        # opt into, so nothing is proposed.
        blueprints = [_blueprint("chore", [_SMOKE])]

        proposal = build_proposal(_manifest(), Path("/x"), blueprints, _report([]))

        assert proposal.blueprint_opt_ins == {}


# ---------------------------------------------------------------------------
# build_proposal — stage (never inferred) and team_hints
# ---------------------------------------------------------------------------


class TestBuildProposalStage:
    def test_stage_is_none_when_not_passed_even_if_manifest_declares_one(self) -> None:
        # stage is ONLY the operator's answer — never inferred from the manifest.
        proposal = build_proposal(_manifest(stage="growth"), Path("/x"), [], _report([]))

        assert proposal.stage is None
        assert proposal.team_hints == []

    def test_stage_and_team_hints_from_real_stage_mix(self) -> None:
        from alc.stagepolicy import STAGE_MIX

        core = STAGE_MIX["growth"]["core"]  # ["builder", "sweeper", "grower"]
        proposal = build_proposal(
            _manifest(),
            Path("/x"),
            [],
            _report([]),
            stage="growth",
            hired_archetypes=["builder"],
        )

        assert proposal.stage == "growth"
        assert proposal.team_hints == [a for a in core if a != "builder"]

    def test_unknown_stage_has_no_mix_and_is_noted(self) -> None:
        proposal = build_proposal(
            _manifest(), Path("/x"), [], _report([]), stage="made-up"
        )

        assert proposal.stage == "made-up"
        assert proposal.team_hints == []
        assert any("mix" in note.lower() for note in proposal.unknowns)


# ---------------------------------------------------------------------------
# render_preview — a pure string, writes nothing
# ---------------------------------------------------------------------------

_MANIFEST_RAW = (
    "version: 1\n"
    "default_engine: mock\n"
    "blueprints_dir: .alc/blueprints\n"
)


class TestRenderPreview:
    def test_contains_rendered_check_set_block_and_summary(self) -> None:
        report = _report([_harvested("test", ["npm", "run", "test"])])
        proposal = build_proposal(_manifest(), Path("/x"), [], report)

        preview = render_preview(proposal, _MANIFEST_RAW, {})

        assert isinstance(preview, str)
        assert "project:" in preview
        assert '["npm", "run", "test"]' in preview
        assert "package.json" in preview  # source_path in the summary table

    def test_stage_shows_as_added_line_in_manifest_diff(self) -> None:
        proposal = build_proposal(
            _manifest(), Path("/x"), [], _report([]), stage="growth"
        )

        preview = render_preview(proposal, _MANIFEST_RAW, {})

        assert "+stage: growth" in preview

    def test_opt_in_note_per_blueprint(self) -> None:
        blueprints = [_blueprint("chore", [_SMOKE]), _blueprint("bug", [_SMOKE])]
        report = _report([_harvested("test", ["npm", "run", "test"])])
        proposal = build_proposal(_manifest(), Path("/x"), blueprints, report)

        preview = render_preview(
            proposal, _MANIFEST_RAW, {"chore": "---\nname: chore\n---\n", "bug": "---\nname: bug\n---\n"}
        )

        assert preview.count("check_set: project") >= 2
        assert "chore" in preview
        assert "bug" in preview

    def test_off_path_binary_renders_commented(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # render_check_set consults scaffold.shutil.which; force everything off PATH.
        monkeypatch.setattr("alc.scaffold.shutil.which", lambda cmd: None)
        report = _report(
            [_harvested("test", ["madeup-runner", "test"], available=False)]
        )
        proposal = build_proposal(_manifest(), Path("/x"), [], report)

        preview = render_preview(proposal, _MANIFEST_RAW, {})

        assert "# - name: test" in preview
        assert "commented" in preview.lower()  # summary flags it too


# ---------------------------------------------------------------------------
# Promotion of scaffold.render_check_set to a public name
# ---------------------------------------------------------------------------


class TestRenderCheckSetPromotion:
    def test_public_name_is_importable(self) -> None:
        from alc.scaffold import render_check_set

        block = render_check_set("project", [("test", ["true"])])
        assert "project:" in block

    def test_private_alias_still_points_at_the_public_name(self) -> None:
        from alc.scaffold import _render_check_set, render_check_set

        assert _render_check_set is render_check_set

    def test_still_comments_off_path_binaries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from alc.scaffold import render_check_set

        monkeypatch.setattr("alc.scaffold.shutil.which", lambda cmd: None)
        block = render_check_set("project", [("lint", ["madeup-linter", "."])])

        assert "# - name: lint" in block
