# test_team_remove.py — `alc team remove`: the exit that `retire` is not.
#
# Membership is "any pack file on disk", so retiring a member never takes it
# off the roster — an operator who tried a pack and wanted it gone had no path
# on either surface (dogfood: the retire question). Removal deletes only files
# byte-identical to what the pack would write today, keeps anything customised,
# and checks a retired loop's archived copy too. These tests drive the CLI and
# the UI service over the SAME shared computation (packs.remove_pack) and
# assert they agree.
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from alc.cli import cmd_team
from alc.packs import hired_archetypes
from alc.scaffold import scaffold
from alc.ui import service
from alc.ui.errors import ApiError


def _ns(**overrides) -> argparse.Namespace:
    defaults = {
        "team_action": "remove",
        "archetype": "sweeper",
        "member": "sweeper",
        "force": False,
        "json": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real `alc init`-scaffolded project, cwd'd into."""
    scaffold(tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestTeamRemove:
    def test_remove_a_fresh_pack_deletes_everything_and_leaves_the_roster(
        self, project: Path, capsys
    ) -> None:
        assert cmd_team(_ns(team_action="hire")) == 0
        assert "sweeper" in hired_archetypes(project)
        capsys.readouterr()

        assert cmd_team(_ns()) == 0

        out = capsys.readouterr().out
        assert "Removed 'sweeper'" in out
        assert "left the roster" in out
        assert "alc team hire sweeper" in out
        assert "sweeper" not in hired_archetypes(project)
        assert not (project / ".alc" / "loops" / "sweep.yaml").exists()

    def test_remove_keeps_a_customised_file_and_the_membership(
        self, project: Path, capsys
    ) -> None:
        assert cmd_team(_ns(team_action="hire")) == 0
        blueprint = project / ".alc" / "blueprints" / "refactor.md"
        blueprint.write_text(blueprint.read_text() + "\ncustom operator note\n")
        capsys.readouterr()

        assert cmd_team(_ns()) == 0

        out = capsys.readouterr().out
        assert "Kept 1 customised file(s)" in out
        assert ".alc/blueprints/refactor.md" in out
        assert "stays on the roster" in out
        assert blueprint.exists(), "a customised file must never be deleted"
        # The kept file is a pack file on disk, so the member stays hired.
        assert "sweeper" in hired_archetypes(project)

    def test_remove_collects_a_retired_loops_archived_copy(
        self, project: Path, capsys
    ) -> None:
        assert cmd_team(_ns(team_action="hire")) == 0
        assert cmd_team(_ns(team_action="retire")) == 0
        retired = project / ".alc" / "loops" / "retired" / "sweep.yaml"
        assert retired.exists()
        capsys.readouterr()

        assert cmd_team(_ns()) == 0

        out = capsys.readouterr().out
        assert ".alc/loops/retired/sweep.yaml" in out
        assert not retired.exists(), "the archived copy is pack content too"
        assert not retired.parent.exists(), "an emptied retired/ should not linger"
        assert "sweeper" not in hired_archetypes(project)

    def test_remove_keeps_a_modified_archived_copy(self, project: Path, capsys) -> None:
        assert cmd_team(_ns(team_action="hire")) == 0
        assert cmd_team(_ns(team_action="retire")) == 0
        retired = project / ".alc" / "loops" / "retired" / "sweep.yaml"
        retired.write_text(retired.read_text() + "\n# tuned by the operator\n")
        capsys.readouterr()

        assert cmd_team(_ns()) == 0

        out = capsys.readouterr().out
        assert "Kept 1 customised file(s)" in out
        assert retired.exists()

    def test_remove_unknown_archetype_is_a_clear_error(self, project: Path, capsys) -> None:
        assert cmd_team(_ns(member="wizard")) == 1
        err = capsys.readouterr().err
        assert "no pack named 'wizard'" in err
        assert "builder" in err  # names the valid ones

    def test_remove_when_nothing_on_disk_is_a_no_op(self, project: Path, capsys) -> None:
        assert cmd_team(_ns(member="grower")) == 0
        out = capsys.readouterr().out
        assert "no pack files on disk" in out

    def test_service_remove_matches_the_cli(self, project: Path) -> None:
        service.team_hire(project, "sweeper")
        blueprint = project / ".alc" / "blueprints" / "map.md"
        blueprint.write_text(blueprint.read_text() + "\ncustom\n")

        result = service.team_remove(project, "sweeper")

        assert ".alc/blueprints/map.md" in result["kept"]
        assert ".alc/blueprints/refactor.md" in result["removed"]
        assert blueprint.exists()
        assert "sweeper" in hired_archetypes(project)

    def test_service_remove_unknown_archetype_is_404(self, project: Path) -> None:
        with pytest.raises(ApiError) as exc:
            service.team_remove(project, "wizard")
        assert exc.value.status == 404


class TestRetiredLoopsInRoster:
    """Both rosters must SAY a loop was archived, not silently drop its line."""

    def test_both_surfaces_report_the_retired_loop(self, project: Path, capsys) -> None:
        assert cmd_team(_ns(team_action="hire")) == 0
        assert cmd_team(_ns(team_action="retire")) == 0
        capsys.readouterr()

        assert cmd_team(_ns(team_action="list", json=True)) == 0
        roster = json.loads(capsys.readouterr().out)
        sweeper = next(m for m in roster if m["archetype"] == "sweeper")
        assert sweeper["loops"] == []
        assert sweeper["retired_loops"] == ["sweep"]

        member = next(
            m
            for m in service.team_roster(project)["members"]
            if m["archetype"] == "sweeper"
        )
        assert member["retired_loops"] == ["sweep"]

    def test_human_roster_names_the_archived_location(self, project: Path, capsys) -> None:
        assert cmd_team(_ns(team_action="hire")) == 0
        assert cmd_team(_ns(team_action="retire")) == 0
        capsys.readouterr()

        assert cmd_team(_ns(team_action="list")) == 0
        out = capsys.readouterr().out
        assert "loops retired: sweep (.alc/loops/retired/)" in out

    def test_a_never_retired_member_reports_no_retired_loops(
        self, project: Path, capsys
    ) -> None:
        assert cmd_team(_ns(team_action="hire", archetype="builder")) == 0
        capsys.readouterr()

        assert cmd_team(_ns(team_action="list", json=True)) == 0
        roster = json.loads(capsys.readouterr().out)
        builder = next(m for m in roster if m["archetype"] == "builder")
        assert builder["retired_loops"] == []

    def test_retire_twice_names_the_archived_location(self, project: Path, capsys) -> None:
        assert cmd_team(_ns(team_action="hire")) == 0
        assert cmd_team(_ns(team_action="retire")) == 0
        capsys.readouterr()

        assert cmd_team(_ns(team_action="retire")) == 0

        out = capsys.readouterr().out
        assert "already" in out
        assert ".alc/loops/retired/" in out
        assert "sweep" in out
