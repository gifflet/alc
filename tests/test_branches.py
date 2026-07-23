# test_branches.py — Hermetic tests for the `alc/*` branch helpers.
# Uses a real LOCAL git repository created in tmp_path; no model is called.
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from alc.branches import AlcBranch, delete_branches, list_alc_branches, prune_worktrees


# ---------------------------------------------------------------------------
# Inline git helpers — mirror the house style (test_merge.py / test_worktree.py).
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


# ---------------------------------------------------------------------------
# list_alc_branches
# ---------------------------------------------------------------------------


class TestListAlcBranchesEmpty:
    def test_no_alc_branches_returns_empty_list(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        assert list_alc_branches(repo) == []


class TestListAlcBranchesLabel:
    def test_label_is_the_segment_between_prefix_and_hex_suffix(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/tick-a1b2c3d4", "a.txt", "a\n")
        _make_branch(repo, "alc/run-11223344", "b.txt", "b\n")
        _make_branch(repo, "alc/fanout-review-deadbeef", "c.txt", "c\n")

        by_name = {b.name: b for b in list_alc_branches(repo)}
        assert by_name["alc/tick-a1b2c3d4"].label == "tick"
        assert by_name["alc/run-11223344"].label == "run"
        assert by_name["alc/fanout-review-deadbeef"].label == "fanout-review"


class TestListAlcBranchesMerged:
    def test_branch_at_head_is_merged_and_unmerged_ahead_is_not(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        # No new commit -> alc/no-op is fully contained in HEAD already.
        _git(repo, "branch", "alc/noop-00000000")
        # A real commit ahead of HEAD -> not contained.
        _make_branch(repo, "alc/ahead-ffffffff", "ahead.txt", "x\n")

        by_name = {b.name: b for b in list_alc_branches(repo)}
        assert by_name["alc/noop-00000000"].merged is True
        assert by_name["alc/ahead-ffffffff"].merged is False


class TestListAlcBranchesCommittedAt:
    def test_committed_at_is_a_positive_epoch_float(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/tick-aaaaaaaa", "a.txt", "a\n")

        branches = list_alc_branches(repo)
        assert len(branches) == 1
        assert isinstance(branches[0], AlcBranch)
        assert branches[0].committed_at > 0


class TestListAlcBranchesMissingGit:
    def test_missing_git_binary_degrades_to_empty_list(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/tick-aaaaaaaa", "a.txt", "a\n")

        def _raise(*args, **kwargs):
            raise FileNotFoundError("git")

        monkeypatch.setattr("alc.branches.subprocess.run", _raise)
        assert list_alc_branches(repo) == []


# ---------------------------------------------------------------------------
# delete_branches
# ---------------------------------------------------------------------------


class TestDeleteBranches:
    def test_deletes_alc_branches_and_returns_their_names(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/tick-aaaaaaaa", "a.txt", "a\n")
        _make_branch(repo, "alc/tick-bbbbbbbb", "b.txt", "b\n")

        deleted = delete_branches(repo, ["alc/tick-aaaaaaaa", "alc/tick-bbbbbbbb"])

        assert set(deleted) == {"alc/tick-aaaaaaaa", "alc/tick-bbbbbbbb"}
        assert not _branch_exists(repo, "alc/tick-aaaaaaaa")
        assert not _branch_exists(repo, "alc/tick-bbbbbbbb")

    def test_refuses_ref_outside_alc_prefix(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        _git(repo, "branch", "feature/not-alc")

        deleted = delete_branches(repo, ["feature/not-alc"])

        assert deleted == []
        assert _branch_exists(repo, "feature/not-alc")

    def test_refuses_the_current_branch(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        _git(repo, "checkout", "-b", "alc/tick-current0")

        deleted = delete_branches(repo, ["alc/tick-current0"])

        assert deleted == []
        assert _branch_exists(repo, "alc/tick-current0")

    def test_missing_git_binary_degrades_to_empty_result(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/tick-aaaaaaaa", "a.txt", "a\n")

        def _raise(*args, **kwargs):
            raise FileNotFoundError("git")

        monkeypatch.setattr("alc.branches.subprocess.run", _raise)
        assert delete_branches(repo, ["alc/tick-aaaaaaaa"]) == []


# ---------------------------------------------------------------------------
# prune_worktrees
# ---------------------------------------------------------------------------


class TestPruneWorktrees:
    def test_prunes_a_removed_worktree_and_returns_the_count(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        wt_path = tmp_path / "wt1"
        _git(repo, "worktree", "add", str(wt_path), "-b", "alc/wt-aaaaaaaa")
        # Delete the worktree directory out from under git, without `worktree remove`.
        import shutil

        shutil.rmtree(wt_path)

        assert prune_worktrees(repo) == 1

    def test_nothing_to_prune_returns_zero(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        assert prune_worktrees(repo) == 0

    def test_missing_git_binary_degrades_to_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _make_git_repo(tmp_path)

        def _raise(*args, **kwargs):
            raise FileNotFoundError("git")

        monkeypatch.setattr("alc.branches.subprocess.run", _raise)
        assert prune_worktrees(repo) == 0
