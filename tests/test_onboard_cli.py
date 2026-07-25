# test_onboard_cli.py — Hermetic tests for `alc onboard`, the CLI that wires the
# pure onboard building blocks (harvest → build_proposal → render_preview →
# apply) into a propose-then-approve flow.
#
# Every test scaffolds a REAL `.alc/` plus a harvestable Makefile (a `test:` and
# `lint:` target → `make test` / `make lint`), then drives cmd_onboard directly
# and asserts against stdout and the bytes on disk. The non-interactive modes
# (--json / --dry-run / --yes) are the primary paths; the interactive path is
# exercised by monkeypatching `input` and the TTY seam.
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from alc.cli import cmd_onboard
from alc.intake import load_blueprint, load_manifest
from alc.scaffold import scaffold


def _ns(**overrides) -> argparse.Namespace:
    defaults = {"dry_run": False, "yes": False, "json": False, "stage": None}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real `alc init`-scaffolded project with a harvestable Makefile, cwd'd into.

    A bare Makefile is not a stack marker, so the scaffolded blueprints stay
    smoke-only (opt-in candidates) while harvest picks up `make test`/`make lint`.
    """
    scaffold(tmp_path)
    (tmp_path / "Makefile").write_text("test:\n\tpytest\n\nlint:\n\truff check\n")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _manifest_text(project_root: Path) -> str:
    return (project_root / ".alc" / "manifest.yaml").read_text()


# ---------------------------------------------------------------------------
# --dry-run: preview only, writes nothing
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_previews_proposal_and_writes_nothing(
        self, project: Path, capsys
    ) -> None:
        before = _manifest_text(project)

        assert cmd_onboard(_ns(dry_run=True)) == 0

        out = capsys.readouterr().out
        assert "alc onboard — proposal preview" in out
        assert "project" in out  # the proposed check_set
        # Not a byte moved on disk.
        assert _manifest_text(project) == before


# ---------------------------------------------------------------------------
# --json: machine-readable proposal, writes nothing
# ---------------------------------------------------------------------------


class TestJson:
    def test_emits_proposal_shape_and_writes_nothing(
        self, project: Path, capsys
    ) -> None:
        before = _manifest_text(project)

        assert cmd_onboard(_ns(json=True)) == 0

        data = json.loads(capsys.readouterr().out)
        assert set(data) >= {"check_sets", "blueprint_opt_ins", "stage", "team_hints"}
        assert "project" in data["check_sets"]
        # The harvested commands survive into the JSON feed.
        commands = [c["command"] for c in data["check_sets"]["project"]]
        assert ["make", "test"] in commands
        assert _manifest_text(project) == before


# ---------------------------------------------------------------------------
# --yes: apply the full proposal non-interactively
# ---------------------------------------------------------------------------


class TestYesApplies:
    def test_yes_stage_growth_applies_and_prints_team_hints(
        self, project: Path, capsys
    ) -> None:
        assert cmd_onboard(_ns(yes=True, stage="growth")) == 0

        out = capsys.readouterr().out
        # The preview's team-hints section is printed before the apply.
        assert "hiring" in out

        reloaded = load_manifest(project / ".alc")
        assert "project" in reloaded.check_sets
        assert reloaded.stage == "growth"

        # A smoke-only blueprint received the `check_set: project` opt-in.
        chore = load_blueprint(project / ".alc" / "blueprints", "chore")
        assert chore.check_set == "project"


# ---------------------------------------------------------------------------
# Non-interactive shell without --yes behaves as dry-run
# ---------------------------------------------------------------------------


class TestNonTtyIsDryRun:
    def test_non_tty_without_yes_previews_and_writes_nothing(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        monkeypatch.setattr("alc.cli._isatty", lambda: False)
        before = _manifest_text(project)

        # No --yes, non-interactive: must never prompt, must write nothing.
        assert cmd_onboard(_ns()) == 0

        out = capsys.readouterr().out
        assert "alc onboard — proposal preview" in out
        assert _manifest_text(project) == before


# ---------------------------------------------------------------------------
# Interactive: three independently-approvable sections
# ---------------------------------------------------------------------------


class TestInteractive:
    def test_approve_all_sections_writes_checks_optins_and_stage(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("alc.cli._isatty", lambda: True)
        # checks: y | opt-ins: y | stage: growth | hire now: n
        answers = iter(["y", "y", "growth", "n"])
        monkeypatch.setattr("builtins.input", lambda *a, **k: next(answers))

        assert cmd_onboard(_ns()) == 0

        reloaded = load_manifest(project / ".alc")
        assert "project" in reloaded.check_sets
        assert reloaded.stage == "growth"

        chore = load_blueprint(project / ".alc" / "blueprints", "chore")
        assert chore.check_set == "project"

    def test_decline_every_section_writes_nothing(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("alc.cli._isatty", lambda: True)
        # checks: n | opt-ins: n | stage: skip
        answers = iter(["n", "n", "skip"])
        monkeypatch.setattr("builtins.input", lambda *a, **k: next(answers))

        manifest_before = _manifest_text(project)
        chore_before = (project / ".alc" / "blueprints" / "chore.md").read_text()

        assert cmd_onboard(_ns()) == 0

        assert _manifest_text(project) == manifest_before
        assert (project / ".alc" / "blueprints" / "chore.md").read_text() == chore_before

    def test_hire_confirm_installs_stage_packs(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("alc.cli._isatty", lambda: True)
        # checks: y | opt-ins: y | stage: growth | hire now: y
        answers = iter(["y", "y", "growth", "y"])
        monkeypatch.setattr("builtins.input", lambda *a, **k: next(answers))

        assert cmd_onboard(_ns()) == 0

        # `_install_stage_packs` hired growth's core combo (builder is one).
        assert (project / ".alc" / "blueprints" / "test.md").is_file()


# ---------------------------------------------------------------------------
# Precondition: an existing `.alc/` operator layer
# ---------------------------------------------------------------------------


class TestRequiresOperatorLayer:
    def test_no_operator_layer_raises_the_standard_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A bare directory with no `.alc/`: `alc onboard` is the follow-up to
        # `alc init`, not a scaffolder — the same FileNotFoundError every command
        # surfaces when the operator layer is missing.
        monkeypatch.chdir(tmp_path)

        with pytest.raises(FileNotFoundError):
            cmd_onboard(_ns(dry_run=True))
