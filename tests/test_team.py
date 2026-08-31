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
        # The post-hire lint no longer calls this scaffold clean: its Blueprints
        # carry only the smoke placeholder, and a pack hired onto checks that
        # verify nothing deserves the warn more, not less. Advisory — the hire
        # itself still succeeds (exit 0 asserted above).
        assert "blueprint-checks-smoke-only" in out

    def test_hire_unknown_archetype_is_a_clear_error(self, project: Path, capsys) -> None:
        assert cmd_team(_ns(team_action="hire", archetype="nosuchpack")) == 1
        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert "nosuchpack" in err
        # Nothing was written.
        assert not (project / ".alc" / "blueprints" / "test.md").exists()

    def test_hire_adds_only_missing_files_and_keeps_existing_bytes(
        self, project: Path, capsys
    ) -> None:
        # Additive by default: a partially-present, CUSTOMIZED pack must receive
        # only the files it lacks — never overwriting the operator's edits. The
        # custom content is a VALID (but non-default) Blueprint so the layer stays
        # lint-clean and the exit code proves the additive path, not a lint fail.
        custom_bytes = (
            "---\n"
            "name: test\n"
            "purpose: My own customized test authoring workflow.\n"
            "compute_tier: standard\n"
            "checks:\n"
            "  - name: smoke\n"
            '    command: ["true"]\n'
            "report:\n"
            "  format: json\n"
            "  schema:\n"
            "    status: string\n"
            "    summary: string\n"
            "archetype: builder\n"
            "---\n\n"
            "## My Custom Test Workflow\n"
        )
        customized = project / ".alc" / "blueprints" / "test.md"
        customized.parent.mkdir(parents=True, exist_ok=True)
        customized.write_text(custom_bytes)

        assert cmd_team(_ns(team_action="hire", archetype="builder")) == 0

        # The customized file kept its exact bytes; the missing files got written.
        assert customized.read_text() == custom_bytes
        assert (project / ".alc" / "blueprints" / "qa.md").is_file()
        assert (project / ".alc" / "flows" / "ship-hardened.yaml").is_file()

        out = capsys.readouterr().out
        # Reports the added missing files and the kept (drifted) one by name.
        assert "added 2 missing file(s)" in out
        assert ".alc/blueprints/qa.md" in out
        assert "kept (already on disk): .alc/blueprints/test.md" in out
        assert "differs from the pack default" in out

    def test_hire_fully_present_is_an_idempotent_no_op(self, project: Path, capsys) -> None:
        # First hire writes everything; a second hire has nothing to add.
        assert cmd_team(_ns(team_action="hire", archetype="builder")) == 0
        capsys.readouterr()

        # Snapshot every pack file's bytes to prove the no-op writes nothing.
        test_md = project / ".alc" / "blueprints" / "test.md"
        before = test_md.read_text()

        assert cmd_team(_ns(team_action="hire", archetype="builder")) == 0
        out = capsys.readouterr().out
        assert "already fully hired" in out
        assert "nothing to add" in out
        assert test_md.read_text() == before  # untouched

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

    def test_list_and_status_agree_on_the_roster(self, project: Path, capsys) -> None:
        # T6: `status` additionally reports Mix Health, so its JSON payload is no
        # longer a bare roster array — but the roster itself must still agree.
        cmd_team(_ns(team_action="hire", archetype="builder"))
        capsys.readouterr()

        assert cmd_team(_ns(team_action="list", json=True)) == 0
        list_payload = json.loads(capsys.readouterr().out)

        assert cmd_team(_ns(team_action="status", json=True)) == 0
        status_payload = json.loads(capsys.readouterr().out)

        assert status_payload["roster"] == list_payload
        assert [m["archetype"] for m in list_payload] == ["builder"]

    def test_status_json_includes_mix_health_with_no_data_yet(
        self, project: Path, capsys
    ) -> None:
        cmd_team(_ns(team_action="hire", archetype="builder"))
        capsys.readouterr()

        assert cmd_team(_ns(team_action="status", json=True)) == 0
        payload = json.loads(capsys.readouterr().out)

        assert payload["mix_health"]["stage"] is None
        assert payload["mix_health"]["total_runs"] == 0
        assert payload["mix_health"]["by_archetype"] == []

    def test_status_human_output_reports_no_data_yet(self, project: Path, capsys) -> None:
        cmd_team(_ns(team_action="hire", archetype="builder"))
        capsys.readouterr()

        assert cmd_team(_ns(team_action="status")) == 0
        out = capsys.readouterr().out
        assert "Mix Health: no data yet" in out

    def test_bare_team_action_none_behaves_as_status(self, project: Path, capsys) -> None:
        # GAP 1: a bare `alc team` (team_action None) opens on the read view —
        # `status` — so the command family never greets the operator with a usage
        # error. Mix Health (status-only) is the tell that it routed to status.
        assert cmd_team(_ns(team_action=None)) == 0
        out = capsys.readouterr().out
        assert "Mix Health: no data yet" in out

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

        # The discovery hint is `alc team list`, not `alc team hire`: it used to
        # name a proper noun and a command three sentences into first contact,
        # competing with the actual next step. It now reads as deferred.
        assert "Optional, later: alc team list" in out
        # The no-stack nudge now points at `alc onboard` as the harvest path.
        assert "alc onboard" in out
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
        assert "grower: hired" in out

    def test_pre_pmf_stage_hires_the_full_promised_combo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        # roadmap-phase-3.md T3: the Prototyper pack completes the five packs, so
        # `alc init --stage pre-pmf` finally installs everything it promises
        # (prototyper + builder + sweeper) instead of reporting prototyper as
        # "not available yet".
        monkeypatch.chdir(tmp_path)

        assert cmd_init(_init_ns(stage="pre-pmf")) == 0
        out = capsys.readouterr().out

        assert (tmp_path / ".alc" / "flows" / "ship-hardened.yaml").is_file()
        assert (tmp_path / ".alc" / "blueprints" / "spike.md").is_file()
        assert "prototyper: hired" in out
        assert "builder: hired" in out
        assert "sweeper: hired" in out
        assert "not available yet" not in out

    def test_strong_pmf_stage_hires_builder(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)

        assert cmd_init(_init_ns(stage="strong-pmf")) == 0
        assert (tmp_path / ".alc" / "blueprints" / "qa.md").is_file()

    def test_stage_hire_is_additive_and_keeps_a_partially_present_pack(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        # `_install_stage_packs` mirrors `alc team hire`: it tops up a pack's
        # MISSING files and keeps existing ones (byte-for-byte), never refusing.
        from alc.cli import _install_stage_packs

        scaffold(tmp_path)
        monkeypatch.chdir(tmp_path)

        customized = tmp_path / ".alc" / "blueprints" / "test.md"
        customized.parent.mkdir(parents=True, exist_ok=True)
        customized.write_text("MY CUSTOM TEST BLUEPRINT")

        _install_stage_packs(tmp_path, "growth", force=False)

        # The customized builder file kept its bytes; its missing sibling landed.
        assert customized.read_text() == "MY CUSTOM TEST BLUEPRINT"
        assert (tmp_path / ".alc" / "blueprints" / "qa.md").is_file()

        out = capsys.readouterr().out
        # builder was partially present: reported as added-with-kept, not refused.
        assert "builder: hired (added" in out
        assert "kept 1 existing" in out
        # sweeper was fully absent: a plain add.
        assert "sweeper: hired (added" in out

    def test_stage_hire_reports_a_fully_present_pack_as_a_no_op(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        from alc.cli import _install_stage_packs

        scaffold(tmp_path)
        monkeypatch.chdir(tmp_path)

        # Hire the whole builder pack, then re-run the stage install.
        _install_stage_packs(tmp_path, "growth", force=False)
        capsys.readouterr()
        _install_stage_packs(tmp_path, "growth", force=False)

        out = capsys.readouterr().out
        assert "builder: already fully hired" in out
        assert "nothing to add" in out

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


# ---------------------------------------------------------------------------
# `alc init` — honest guidance when no stack is detected.
# ---------------------------------------------------------------------------


class TestInitStacklessNudge:
    def test_stackless_init_prints_an_honest_nudge(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        # Empty dir -> no stack detected -> the nudge fires.
        monkeypatch.chdir(tmp_path)
        assert cmd_init(_init_ns()) == 0
        out = capsys.readouterr().out
        assert "No known stack detected" in out
        assert "alc checks audit" in out

    def test_detected_stack_init_does_not_print_the_nudge(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        (tmp_path / "go.mod").write_text("module example\n")
        monkeypatch.chdir(tmp_path)
        assert cmd_init(_init_ns()) == 0
        out = capsys.readouterr().out
        assert "No known stack detected" not in out
        assert "Detected Go" in out
