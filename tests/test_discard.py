# test_discard.py — Hermetic tests for `alc discard`: branches, worktrees, bundles.
# Uses a real LOCAL git repository created in tmp_path; no model is called.
from __future__ import annotations

import argparse
import subprocess
import time
from pathlib import Path

import pytest

from alc.cli import cmd_discard

# ---------------------------------------------------------------------------
# Inline git helpers — mirror the house style (test_branches.py / test_land.py).
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


def _make_branch(repo: Path, branch: str, filename: str, content: str) -> None:
    """Create *branch* off main, commit *content* to *filename*, then check out main."""
    _git(repo, "checkout", "-b", branch, "main")
    (repo / filename).write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", f"feat(auto): {branch}")
    _git(repo, "checkout", "main")


def _branch_exists(repo: Path, branch: str) -> bool:
    return _git(repo, "branch", "--list", branch).stdout.strip() != ""


def _ns(**overrides) -> argparse.Namespace:
    defaults = {
        "branch": [],
        "all_unmerged": False,
        "worktrees": False,
        "bundles": False,
        "older_than": None,
        "yes": False,
        "json": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


_MANIFEST = """\
version: 1
default_engine: mock
compute_tiers:
  standard:
    mock: mock-small
engines:
  mock:
    type: mock
"""


def _make_alc_dir(repo: Path) -> Path:
    """Write a minimal .alc/manifest.yaml (default bundles_dir) into *repo*."""
    alc = repo / ".alc"
    alc.mkdir()
    (alc / "manifest.yaml").write_text(_MANIFEST)
    return alc


# ---------------------------------------------------------------------------
# No arguments — list the unmerged alc/* branches with age + provenance.
# ---------------------------------------------------------------------------


class TestDiscardListPath:
    def test_no_unmerged_branches_prints_message(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)

        assert cmd_discard(_ns()) == 0
        assert "No unmerged alc/ branches." in capsys.readouterr().out

    def test_lists_unmerged_branches_with_age_and_label(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/tick-aaaaaaaa", "a.txt", "a\n")
        monkeypatch.chdir(repo)

        assert cmd_discard(_ns()) == 0
        out = capsys.readouterr().out
        assert "alc/tick-aaaaaaaa" in out
        assert "tick" in out
        assert "d old" in out
        assert "Run: alc discard --all-unmerged" in out

    def test_json_output_is_machine_readable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        import json

        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/tick-aaaaaaaa", "a.txt", "a\n")
        monkeypatch.chdir(repo)

        assert cmd_discard(_ns(json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, list) and len(data) == 1
        assert data[0]["name"] == "alc/tick-aaaaaaaa"

    def test_outside_git_repo_is_a_clear_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        non_repo = tmp_path / "not-a-repo"
        non_repo.mkdir()
        monkeypatch.chdir(non_repo)

        assert cmd_discard(_ns()) == 1
        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert "not inside a git repository" in err


# ---------------------------------------------------------------------------
# Confirmation gating — never delete silently.
# ---------------------------------------------------------------------------


class TestDiscardConfirmation:
    def test_non_tty_without_yes_refuses(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/tick-aaaaaaaa", "a.txt", "a\n")
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        assert cmd_discard(_ns(branch=["alc/tick-aaaaaaaa"])) == 1
        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert "confirmation" in err
        # Nothing was deleted.
        assert _branch_exists(repo, "alc/tick-aaaaaaaa")

    def test_yes_flag_skips_the_prompt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/tick-aaaaaaaa", "a.txt", "a\n")
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        assert cmd_discard(_ns(branch=["alc/tick-aaaaaaaa"], yes=True)) == 0
        assert not _branch_exists(repo, "alc/tick-aaaaaaaa")

    def test_tty_prompt_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/tick-aaaaaaaa", "a.txt", "a\n")
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda prompt="": "y")

        assert cmd_discard(_ns(branch=["alc/tick-aaaaaaaa"])) == 0
        assert not _branch_exists(repo, "alc/tick-aaaaaaaa")

    def test_tty_prompt_declined_refuses(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/tick-aaaaaaaa", "a.txt", "a\n")
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda prompt="": "n")

        assert cmd_discard(_ns(branch=["alc/tick-aaaaaaaa"])) == 1
        assert _branch_exists(repo, "alc/tick-aaaaaaaa")


# ---------------------------------------------------------------------------
# Branch deletion — explicit names, --all-unmerged, and refusals delegated
# to delete_branches (non-alc/ ref, current branch).
# ---------------------------------------------------------------------------


class TestDiscardBranches:
    def test_deletes_the_named_branch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/tick-aaaaaaaa", "a.txt", "a\n")
        _make_branch(repo, "alc/tick-bbbbbbbb", "b.txt", "b\n")
        monkeypatch.chdir(repo)

        assert cmd_discard(_ns(branch=["alc/tick-aaaaaaaa"], yes=True)) == 0
        assert not _branch_exists(repo, "alc/tick-aaaaaaaa")
        assert _branch_exists(repo, "alc/tick-bbbbbbbb")

    def test_all_unmerged_deletes_every_unmerged_branch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/tick-aaaaaaaa", "a.txt", "a\n")
        _make_branch(repo, "alc/tick-bbbbbbbb", "b.txt", "b\n")
        monkeypatch.chdir(repo)

        assert cmd_discard(_ns(all_unmerged=True, yes=True)) == 0
        assert not _branch_exists(repo, "alc/tick-aaaaaaaa")
        assert not _branch_exists(repo, "alc/tick-bbbbbbbb")

    def test_rejects_a_non_alc_branch_before_touching_anything(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _git(repo, "branch", "feature/not-alc")
        monkeypatch.chdir(repo)

        assert cmd_discard(_ns(branch=["feature/not-alc"], yes=True)) == 1
        err = capsys.readouterr().err
        assert "not an alc/ branch" in err
        assert _branch_exists(repo, "feature/not-alc")


# ---------------------------------------------------------------------------
# --worktrees — prune stale worktree admin entries.
# ---------------------------------------------------------------------------


class TestDiscardWorktrees:
    def test_prunes_a_removed_worktree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        import shutil

        repo = _make_git_repo(tmp_path)
        wt_path = tmp_path / "wt1"
        _git(repo, "worktree", "add", str(wt_path), "-b", "alc/wt-aaaaaaaa")
        shutil.rmtree(wt_path)
        monkeypatch.chdir(repo)

        # No confirmation required — pruning stale admin entries is not
        # destructive to any committed or uncommitted work.
        assert cmd_discard(_ns(worktrees=True)) == 0
        assert "Pruned 1 stale worktree" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# --bundles --older-than N — delete old bundle files.
# ---------------------------------------------------------------------------


class TestDiscardBundles:
    def test_requires_older_than(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _make_alc_dir(repo)
        monkeypatch.chdir(repo)

        assert cmd_discard(_ns(bundles=True)) == 1
        err = capsys.readouterr().err
        assert "--bundles requires --older-than" in err

    def test_deletes_bundles_older_than_n_days(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _make_alc_dir(repo)
        bundles_dir = repo / ".alc" / "bundles"
        bundles_dir.mkdir()

        old_bundle = bundles_dir / "old.jsonl"
        old_bundle.write_text("{}\n")
        new_bundle = bundles_dir / "new.jsonl"
        new_bundle.write_text("{}\n")

        old_time = time.time() - 40 * 86400
        import os

        os.utime(old_bundle, (old_time, old_time))

        monkeypatch.chdir(repo)

        assert cmd_discard(_ns(bundles=True, older_than=30, yes=True)) == 0
        assert not old_bundle.exists()
        assert new_bundle.exists()
        assert "Deleted 1 bundle file(s)" in capsys.readouterr().out

    def test_missing_bundles_dir_deletes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _make_alc_dir(repo)
        monkeypatch.chdir(repo)

        assert cmd_discard(_ns(bundles=True, older_than=30, yes=True)) == 0
        assert "Deleted 0 bundle file(s)" in capsys.readouterr().out
