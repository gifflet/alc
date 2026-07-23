# test_land.py — Hermetic tests for `alc land`: a thin shell over auto_merge_branches.
# Uses a real LOCAL git repository created in tmp_path; no model is called.
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest

from alc.cli import cmd_land

# ---------------------------------------------------------------------------
# Inline git helpers — mirror the house style (test_branches.py / test_merge.py).
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command against *repo*, returning the completed process."""
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _make_git_repo(base: Path) -> Path:
    """Initialize a git repo with one seed commit on main and return its path."""
    repo = base / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.email", "test@alc.local")
    _git(repo, "config", "user.name", "ALC Test")
    (repo / "seed.txt").write_text("line-a\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    return repo


def _make_branch(repo: Path, branch: str, filename: str, content: str, subject: str) -> None:
    """Create *branch* off main, commit *content* to *filename*, then check out main."""
    _git(repo, "checkout", "-b", branch, "main")
    (repo / filename).write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", subject)
    _git(repo, "checkout", "main")


def _branch_exists(repo: Path, branch: str) -> bool:
    return _git(repo, "branch", "--list", branch).stdout.strip() != ""


def _ns(**overrides) -> argparse.Namespace:
    defaults = {"branch": [], "all": False, "json": False}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# No arguments — list the unmerged alc/* branches.
# ---------------------------------------------------------------------------


class TestLandListPath:
    def test_no_unmerged_branches_prints_message(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)

        assert cmd_land(_ns()) == 0
        assert "No unmerged alc/ branches." in capsys.readouterr().out

    def test_lists_unmerged_branches_with_hint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/tick-aaaaaaaa", "a.txt", "a\n", "feat(auto): a")
        monkeypatch.chdir(repo)

        assert cmd_land(_ns()) == 0
        out = capsys.readouterr().out
        assert "alc/tick-aaaaaaaa" in out
        assert "(tick)" in out
        assert "Run: alc land --all" in out

    def test_json_output_is_machine_readable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        import json

        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/tick-aaaaaaaa", "a.txt", "a\n", "feat(auto): a")
        monkeypatch.chdir(repo)

        assert cmd_land(_ns(json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, list) and len(data) == 1
        assert data[0]["name"] == "alc/tick-aaaaaaaa"
        assert data[0]["label"] == "tick"
        assert data[0]["merged"] is False


# ---------------------------------------------------------------------------
# --all — integrate every unmerged alc/* branch.
# ---------------------------------------------------------------------------


class TestLandAll:
    def test_merges_every_unmerged_branch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/tick-aaa", "a.txt", "a\n", "feat(auto): a")
        _make_branch(repo, "alc/tick-bbb", "b.txt", "b\n", "feat(auto): b")
        monkeypatch.chdir(repo)

        assert cmd_land(_ns(all=True)) == 0
        out = capsys.readouterr().out
        assert "merged 2, left 0 for manual resolution" in out
        assert not _branch_exists(repo, "alc/tick-aaa")
        assert not _branch_exists(repo, "alc/tick-bbb")

    def test_conflicted_branch_left_intact_and_exit_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        # Both branches rewrite seed.txt line 1 differently -> conflict on the second.
        _make_branch(
            repo, "alc/tick-aaa", "seed.txt", "from-a\n", "feat(auto): change from a"
        )
        _make_branch(
            repo, "alc/tick-bbb", "seed.txt", "from-b\n", "feat(auto): change from b"
        )
        monkeypatch.chdir(repo)

        assert cmd_land(_ns(all=True)) == 1
        out = capsys.readouterr().out
        assert "left 1 for manual resolution" in out
        assert _branch_exists(repo, "alc/tick-bbb")


# ---------------------------------------------------------------------------
# Explicit branch names.
# ---------------------------------------------------------------------------


class TestLandExplicitBranches:
    def test_integrates_the_named_branch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/tick-aaa", "a.txt", "a\n", "feat(auto): a")
        # A second unmerged branch that must be left ALONE (not named).
        _make_branch(repo, "alc/tick-bbb", "b.txt", "b\n", "feat(auto): b")
        monkeypatch.chdir(repo)

        assert cmd_land(_ns(branch=["alc/tick-aaa"])) == 0
        assert not _branch_exists(repo, "alc/tick-aaa")
        assert _branch_exists(repo, "alc/tick-bbb")

    def test_rejects_a_non_alc_branch_before_touching_anything(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _git(repo, "branch", "feature/not-alc")
        monkeypatch.chdir(repo)

        assert cmd_land(_ns(branch=["feature/not-alc"])) == 1
        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert "not an alc/ branch" in err
        # Untouched — the branch is still there.
        assert _branch_exists(repo, "feature/not-alc")

    def test_prefix_validated_even_outside_a_git_repository(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        non_repo = tmp_path / "not-a-repo"
        non_repo.mkdir()
        monkeypatch.chdir(non_repo)

        assert cmd_land(_ns(branch=["not-alc-at-all"])) == 1
        err = capsys.readouterr().err
        assert "not an alc/ branch" in err


# ---------------------------------------------------------------------------
# Outside a git repository.
# ---------------------------------------------------------------------------


class TestLandOutsideGitRepo:
    def test_no_args_outside_git_repo_is_a_clear_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        non_repo = tmp_path / "not-a-repo"
        non_repo.mkdir()
        monkeypatch.chdir(non_repo)

        assert cmd_land(_ns()) == 1
        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert "not inside a git repository" in err
