# test_init_output_order.py — what `alc init` says, and in what order.
#
# Two E2E findings. "Archetype Packs" arrived as a capitalised proper noun three
# sentences into first contact, offered alongside the real next step — so it
# competed with `Next:` and cost a beat to decide it was not for you yet. And the
# scaffolded lint check pointed at an unpinned `ruff` on a repo whose own CI pins
# `uvx ruff@0.15.21`: following the advice installs a tool that can disagree with
# the pipeline that actually gates the project.
from __future__ import annotations

import argparse
from pathlib import Path

from alc.cli import cmd_init
from alc.scaffold import detect_ci_config


def _ns(**overrides) -> argparse.Namespace:
    defaults = {"force": False, "engine": None, "stage": None, "setup": False}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _python_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.1.0"\n')
    return tmp_path


class TestDetectCiConfig:
    def test_finds_a_github_workflow(self, tmp_path: Path) -> None:
        wf = tmp_path / ".github/workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text("name: ci\n")

        assert detect_ci_config(tmp_path) == ".github/workflows/ci.yml"

    def test_finds_gitlab_and_circle_too(self, tmp_path: Path) -> None:
        (tmp_path / ".gitlab-ci.yml").write_text("stages: []\n")

        assert detect_ci_config(tmp_path) == ".gitlab-ci.yml"

    def test_none_when_the_project_has_no_ci(self, tmp_path: Path) -> None:
        assert detect_ci_config(tmp_path) is None

    def test_a_directory_named_like_a_config_is_not_one(self, tmp_path: Path) -> None:
        (tmp_path / ".gitlab-ci.yml").mkdir()

        assert detect_ci_config(tmp_path) is None

    def test_it_never_reads_the_file(self, tmp_path: Path) -> None:
        # Existence only: alc does not parse CI configs (harvest.py keeps that
        # out of scope), so an unparseable one must not raise.
        wf = tmp_path / ".github/workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_bytes(b"\xff\xfe not yaml at all")

        assert detect_ci_config(tmp_path) == ".github/workflows/ci.yml"


class TestInitDefersTheOptionalOffer:
    def test_the_last_line_is_the_one_next_action(self, tmp_path: Path, monkeypatch, capsys) -> None:
        monkeypatch.chdir(_python_project(tmp_path))

        assert cmd_init(_ns()) == 0
        lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
        assert lines[-1].startswith("Next:")

    def test_the_team_offer_is_marked_as_later(self, tmp_path: Path, monkeypatch, capsys) -> None:
        monkeypatch.chdir(_python_project(tmp_path))

        assert cmd_init(_ns()) == 0
        out = capsys.readouterr().out
        offer = next(line for line in out.splitlines() if "alc team list" in line)
        assert offer.startswith("Optional, later:")

    def test_it_no_longer_opens_with_an_undefined_proper_noun(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(_python_project(tmp_path))

        assert cmd_init(_ns()) == 0
        assert "Archetype Packs" not in capsys.readouterr().out


class TestInitPointsAtTheProjectsOwnCi:
    def test_it_names_the_ci_file_when_there_is_one(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        project = _python_project(tmp_path)
        wf = project / ".github/workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text("name: ci\n")
        monkeypatch.chdir(project)

        assert cmd_init(_ns()) == 0
        out = capsys.readouterr().out
        assert ".github/workflows/ci.yml" in out
        assert "version-pinned" in out

    def test_it_stays_quiet_when_the_project_has_no_ci(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(_python_project(tmp_path))

        assert cmd_init(_ns()) == 0
        assert "version-pinned" not in capsys.readouterr().out

    def test_the_ci_note_comes_before_the_next_action(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        project = _python_project(tmp_path)
        wf = project / ".github/workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text("name: ci\n")
        monkeypatch.chdir(project)

        assert cmd_init(_ns()) == 0
        out = capsys.readouterr().out
        assert out.index("version-pinned") < out.index("Next:")
