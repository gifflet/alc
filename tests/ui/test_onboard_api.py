# test_onboard_api.py — GET /checks/onboard and POST /checks/onboard/apply: the
# harvest-only `alc onboard` proposal + apply, surfaced in the Checks view. The
# routes reuse the pure onboard core (harvest -> build_proposal -> apply); the
# engine `--assist` path stays CLI-only and is never wired here.
from __future__ import annotations

from pathlib import Path

import pytest

from alc.intake import load_blueprint, load_manifest
from alc.onboard import ApplyResult
from alc.policy import Violation
from alc.ui import service
from alc.ui.errors import ApiError


def _add_makefile(project: Path) -> None:
    """Give *project* a harvestable Makefile (a `test:` and `lint:` target).

    A bare Makefile is not a stack marker, so the scaffolded blueprints stay
    smoke-only (opt-in candidates) while harvest picks up `make test`/`make lint`.
    """
    (project / "Makefile").write_text("test:\n\tpytest\n\nlint:\n\truff check\n")


# ---------------------------------------------------------------------------
# GET /checks/onboard — the proposal (writes nothing)
# ---------------------------------------------------------------------------


class TestOnboardProposal:
    def test_harvestable_project_proposes_the_project_set_and_opt_ins(
        self, client, registered: str, project: Path
    ) -> None:
        _add_makefile(project)

        resp = client.get(f"/api/projects/{registered}/checks/onboard")
        assert resp.status_code == 200
        body = resp.json()

        project_set = body["check_sets"]["project"]
        assert {c["name"] for c in project_set} == {"test", "lint"}
        # The harvested command survives into the JSON feed, with origin "harvest".
        by_name = {c["name"]: c for c in project_set}
        assert by_name["test"]["command"] == ["make", "test"]
        assert all(c["origin"] == "harvest" for c in project_set)

        # Every smoke-only blueprint opts into the new `project` set (never `plan`).
        assert body["blueprint_opt_ins"] == {
            "bug": "project",
            "chore": "project",
            "feature": "project",
        }

    def test_bare_project_has_empty_check_sets_and_the_empty_harvest_note(
        self, client, registered: str
    ) -> None:
        resp = client.get(f"/api/projects/{registered}/checks/onboard")
        assert resp.status_code == 200
        body = resp.json()

        assert body["check_sets"] == {}
        assert body["blueprint_opt_ins"] == {}
        assert any("no existing check" in note.lower() for note in body["unknowns"])

    def test_staged_proposal_surfaces_team_hints_stageless_does_not(
        self, client, registered: str
    ) -> None:
        # Nothing hired in a fresh scaffold, so every core archetype is a hint.
        staged = client.get(
            f"/api/projects/{registered}/checks/onboard", params={"stage": "growth"}
        ).json()
        assert staged["stage"] == "growth"
        assert staged["team_hints"] == ["builder", "sweeper", "grower"]

        stageless = client.get(f"/api/projects/{registered}/checks/onboard").json()
        assert stageless["stage"] is None
        assert stageless["team_hints"] == []

    def test_an_unaccepted_stage_is_rejected(self, client, registered: str) -> None:
        resp = client.get(
            f"/api/projects/{registered}/checks/onboard", params={"stage": "made-up"}
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /checks/onboard/apply — the only writer (append-only, gate-first)
# ---------------------------------------------------------------------------


class TestOnboardApply:
    def test_apply_writes_the_manifest_and_opts_blueprints_in(
        self, client, registered: str, project: Path
    ) -> None:
        _add_makefile(project)

        resp = client.post(
            f"/api/projects/{registered}/checks/onboard/apply", json={"stage": "growth"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["applied"] is True
        assert body["sets_added"] == ["project"]
        assert body["stage_set"] is True
        assert set(body["blueprints_opted_in"]) == {"bug", "chore", "feature"}

        # The bytes on disk actually moved: the `project` set and the stage line.
        reloaded = load_manifest(project / ".alc")
        assert "project" in reloaded.check_sets
        assert reloaded.stage == "growth"
        chore = load_blueprint(project / ".alc" / "blueprints", "chore")
        assert chore.check_set == "project"

    def test_apply_without_a_stage_leaves_the_stage_unset(
        self, client, registered: str, project: Path
    ) -> None:
        _add_makefile(project)

        resp = client.post(
            f"/api/projects/{registered}/checks/onboard/apply", json={}
        )
        assert resp.status_code == 200
        assert resp.json()["stage_set"] is False
        assert load_manifest(project / ".alc").stage is None

    def test_an_unaccepted_stage_is_rejected(self, client, registered: str) -> None:
        resp = client.post(
            f"/api/projects/{registered}/checks/onboard/apply", json={"stage": "made-up"}
        )
        assert resp.status_code == 422

    def test_a_second_apply_is_a_clean_no_op_with_no_duplicate_keys(
        self, client, registered: str, project: Path
    ) -> None:
        # Clicking "Adopt" twice must be safe: the second apply adds NOTHING (the
        # server rebuilds the proposal from the now-onboarded manifest), and the
        # manifest keeps exactly ONE `project:` block and ONE `stage:` line.
        _add_makefile(project)
        url = f"/api/projects/{registered}/checks/onboard/apply"

        first = client.post(url, json={"stage": "growth"})
        assert first.status_code == 200
        assert first.json()["applied"] is True
        after_first = (project / ".alc" / "manifest.yaml").read_text()

        second = client.post(url, json={"stage": "growth"})
        assert second.status_code == 200
        body = second.json()
        assert body["applied"] is False
        assert body["sets_added"] == []
        assert body["stage_set"] is False
        assert body["notes"]  # an honest "nothing new" note

        # Not a byte moved, and there is no duplicate key on disk.
        after_second = (project / ".alc" / "manifest.yaml").read_text()
        assert after_second == after_first
        assert after_second.split("\n").count("  project:") == 1
        assert after_second.split("\n").count("stage: growth") == 1

    def test_proposal_after_adoption_suppresses_the_project_set(
        self, client, registered: str, project: Path
    ) -> None:
        # Once adopted, GET /checks/onboard must reflect the live set honestly:
        # empty check_sets, and the DISTINCT "already exists" note in unknowns
        # (never the empty-harvest claim, which would be wrong here).
        _add_makefile(project)
        client.post(
            f"/api/projects/{registered}/checks/onboard/apply", json={"stage": "growth"}
        )

        body = client.get(f"/api/projects/{registered}/checks/onboard").json()

        assert body["check_sets"] == {}
        assert body["blueprint_opt_ins"] == {}
        assert any("already exist" in note.lower() for note in body["unknowns"])
        assert not any("no existing check" in note.lower() for note in body["unknowns"])


class TestOnboardApplyBlocked:
    """A blocked apply (the shared gate rejected the candidate — nothing written)
    maps to ApiError(422) carrying the violations, mirroring write_manifest."""

    def test_service_maps_a_violations_result_to_a_422(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        blocked = ApplyResult(
            applied=False,
            sets_added=[],
            blueprints_opted_in=[],
            stage_set=False,
            violations=[
                Violation(rule="check-sets-nonempty", severity="error", message="boom")
            ],
            notes=[],
        )
        monkeypatch.setattr(service.onboard_core, "apply", lambda *a, **k: blocked)

        with pytest.raises(ApiError) as excinfo:
            service.onboard_apply(project, stage=None)

        error = excinfo.value
        assert error.status == 422
        assert error.detail == [
            {"rule": "check-sets-nonempty", "severity": "error", "message": "boom"}
        ]
