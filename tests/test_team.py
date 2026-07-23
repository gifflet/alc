# test_team.py — Hermetic tests for `alc team hire|list|retire|status` and for
# `alc init --stage`, which hires a stage's pack combo via the same machinery.
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from alc.cli import cmd_init, cmd_team
from alc.intake import load_manifest
from alc.loop import loops_dir, save_loop_state, state_path
from alc.models import LoopState
from alc.scaffold import scaffold


def _ns(**overrides) -> argparse.Namespace:
    defaults = {
        "team_action": "hire",
        "archetype": "builder",
        "member": "builder",
        "force": False,
        "json": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _init_ns(**overrides) -> argparse.Namespace:
    defaults = {"force": False, "setup": False, "engine": "claude-code", "stage": None}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real `alc init`-scaffolded project, cwd'd into."""
    scaffold(tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# hire
# ---------------------------------------------------------------------------


class TestTeamHire:
    def test_hire_writes_pack_files_and_lints_clean(self, project: Path, capsys) -> None:
        assert cmd_team(_ns(team_action="hire", archetype="builder")) == 0

        assert (project / ".alc" / "blueprints" / "test.md").is_file()
        assert (project / ".alc" / "blueprints" / "qa.md").is_file()
        assert (project / ".alc" / "flows" / "ship-hardened.yaml").is_file()

        out = capsys.readouterr().out
        assert "Hired 'builder'" in out
        assert "No violations found" in out

    def test_hire_unknown_archetype_is_a_clear_error(self, project: Path, capsys) -> None:
        assert cmd_team(_ns(team_action="hire", archetype="nosuchpack")) == 1
        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert "nosuchpack" in err
        # Nothing was written.
        assert not (project / ".alc" / "blueprints" / "test.md").exists()

    def test_hire_refuses_to_overwrite_without_force(self, project: Path, capsys) -> None:
        assert cmd_team(_ns(team_action="hire", archetype="builder")) == 0
        capsys.readouterr()

        assert cmd_team(_ns(team_action="hire", archetype="builder")) == 1
        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert "--force" in err

    def test_hire_force_overwrites_existing_files(self, project: Path) -> None:
        assert cmd_team(_ns(team_action="hire", archetype="builder")) == 0

        target = project / ".alc" / "blueprints" / "test.md"
        target.write_text("garbage")

        assert cmd_team(_ns(team_action="hire", archetype="builder", force=True)) == 0
        assert "name: test" in target.read_text()


# ---------------------------------------------------------------------------
# list / status
# ---------------------------------------------------------------------------


class TestTeamListStatus:
    def test_no_members_hired_yet(self, project: Path, capsys) -> None:
        assert cmd_team(_ns(team_action="list")) == 0
        assert "No members hired" in capsys.readouterr().out

    def test_list_and_status_return_the_same_roster(self, project: Path, capsys) -> None:
        cmd_team(_ns(team_action="hire", archetype="builder"))
        capsys.readouterr()

        assert cmd_team(_ns(team_action="list", json=True)) == 0
        list_payload = json.loads(capsys.readouterr().out)

        assert cmd_team(_ns(team_action="status", json=True)) == 0
        status_payload = json.loads(capsys.readouterr().out)

        assert list_payload == status_payload
        assert [m["archetype"] for m in list_payload] == ["builder"]

    def test_json_payload_lists_the_pack_files_and_empty_loops(
        self, project: Path, capsys
    ) -> None:
        cmd_team(_ns(team_action="hire", archetype="builder"))
        capsys.readouterr()

        cmd_team(_ns(team_action="list", json=True))
        payload = json.loads(capsys.readouterr().out)

        member = payload[0]
        assert member["archetype"] == "builder"
        assert ".alc/blueprints/test.md" in member["files"]
        assert ".alc/blueprints/qa.md" in member["files"]
        assert member["loops"] == []  # the Builder pack (Wave 2) brings no loops

    def test_human_output_names_the_hired_member(self, project: Path, capsys) -> None:
        cmd_team(_ns(team_action="hire", archetype="builder"))
        capsys.readouterr()

        assert cmd_team(_ns(team_action="list")) == 0
        out = capsys.readouterr().out
        assert "builder" in out
        assert "loops: (none)" in out

    def test_a_pack_with_a_loop_surfaces_its_state(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        from alc import packs

        monkeypatch.setitem(
            packs.PACKS, "sweeper", lambda _stacks: {".alc/loops/sweep.yaml": "name: sweep\n"}
        )

        manifest = load_manifest(project / ".alc")
        loops = loops_dir(manifest, project / ".alc")
        loops.mkdir(parents=True, exist_ok=True)
        (loops / "sweep.yaml").write_text("name: sweep\n")
        save_loop_state(
            state_path(loops, "sweep"), LoopState(name="sweep", status="running", cycle=3)
        )

        assert cmd_team(_ns(team_action="list", json=True)) == 0
        payload = json.loads(capsys.readouterr().out)

        sweeper = next(m for m in payload if m["archetype"] == "sweeper")
        assert sweeper["loops"] == [
            {"name": "sweep", "status": "running", "cycle": 3, "stopped_reason": None}
        ]


# ---------------------------------------------------------------------------
# retire
# ---------------------------------------------------------------------------


class TestTeamRetire:
    def test_retire_unknown_archetype_is_a_clear_error(self, project: Path, capsys) -> None:
        assert cmd_team(_ns(team_action="retire", member="nosuchpack")) == 1
        assert "[ERROR]" in capsys.readouterr().err

    def test_retire_a_pack_with_no_loops_is_a_no_op(self, project: Path, capsys) -> None:
        cmd_team(_ns(team_action="hire", archetype="builder"))
        capsys.readouterr()

        assert cmd_team(_ns(team_action="retire", member="builder")) == 0
        assert "no loop" in capsys.readouterr().out.lower()

    def test_retire_archives_the_loop_yaml_instead_of_deleting_it(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        from alc import packs

        monkeypatch.setitem(
            packs.PACKS, "sweeper", lambda _stacks: {".alc/loops/sweep.yaml": "name: sweep\n"}
        )

        manifest = load_manifest(project / ".alc")
        loops = loops_dir(manifest, project / ".alc")
        loops.mkdir(parents=True, exist_ok=True)
        (loops / "sweep.yaml").write_text("name: sweep\n")

        assert cmd_team(_ns(team_action="retire", member="sweeper")) == 0

        assert not (loops / "sweep.yaml").exists()
        assert (loops / "retired" / "sweep.yaml").is_file()
        out = capsys.readouterr().out
        assert "sweep.yaml" in out

    def test_retire_preserves_the_loop_state_for_audit(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from alc import packs

        monkeypatch.setitem(
            packs.PACKS, "sweeper", lambda _stacks: {".alc/loops/sweep.yaml": "name: sweep\n"}
        )

        manifest = load_manifest(project / ".alc")
        loops = loops_dir(manifest, project / ".alc")
        loops.mkdir(parents=True, exist_ok=True)
        (loops / "sweep.yaml").write_text("name: sweep\n")
        save_loop_state(
            state_path(loops, "sweep"), LoopState(name="sweep", status="running", cycle=2)
        )

        cmd_team(_ns(team_action="retire", member="sweeper"))

        assert state_path(loops, "sweep").is_file()

    def test_retire_a_pack_with_no_files_at_all_on_disk_is_a_no_op(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        from alc import packs

        monkeypatch.setitem(
            packs.PACKS, "sweeper", lambda _stacks: {".alc/loops/sweep.yaml": "name: sweep\n"}
        )

        assert cmd_team(_ns(team_action="retire", member="sweeper")) == 0
        assert "no loop" in capsys.readouterr().out.lower()


# ---------------------------------------------------------------------------
# `alc init --stage` — sugar over the same pack machinery.
# ---------------------------------------------------------------------------


class TestInitStage:
    def test_no_stage_prints_a_discovery_hint_and_installs_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        monkeypatch.chdir(tmp_path)

        assert cmd_init(_init_ns()) == 0
        out = capsys.readouterr().out

        assert "alc team hire" in out
        assert not (tmp_path / ".alc" / "blueprints" / "test.md").exists()

    def test_stage_hires_the_available_packs_and_reports_the_rest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        monkeypatch.chdir(tmp_path)

        assert cmd_init(_init_ns(stage="growth")) == 0
        out = capsys.readouterr().out

        assert (tmp_path / ".alc" / "blueprints" / "test.md").is_file()
        assert "builder: hired" in out
        assert "sweeper: hired" in out
        assert "maintainer: hired" in out
        # `grower` is a later wave — still reported plainly, not installed.
        assert "grower: not available yet" in out

    def test_pre_pmf_stage_hires_builder(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)

        assert cmd_init(_init_ns(stage="pre-pmf")) == 0
        assert (tmp_path / ".alc" / "flows" / "ship-hardened.yaml").is_file()

    def test_strong_pmf_stage_hires_builder(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)

        assert cmd_init(_init_ns(stage="strong-pmf")) == 0
        assert (tmp_path / ".alc" / "blueprints" / "qa.md").is_file()

    def test_stage_hire_produces_a_lint_clean_layer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from alc.intake import load_all_blueprints, load_manifest
        from alc.policy import lint

        monkeypatch.chdir(tmp_path)
        assert cmd_init(_init_ns(stage="growth")) == 0

        operator_layer = tmp_path / ".alc"
        manifest = load_manifest(operator_layer)
        blueprints = load_all_blueprints(manifest, operator_layer)
        errors = [v for v in lint(manifest, blueprints) if v.severity == "error"]
        assert not errors, errors
