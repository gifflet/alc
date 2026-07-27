# test_variants.py — Hermetic tests for the variants archive helpers.
# `mark_live` annotates compare-surface rows with branch liveness; it is exercised
# against a real LOCAL git repo created in tmp_path (no model is ever called).
from __future__ import annotations

import subprocess
from pathlib import Path

from alc.variants import mark_live

# ---------------------------------------------------------------------------
# Inline git helpers — mirror the house style (test_branches.py).
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _make_git_repo(base: Path) -> Path:
    repo = base / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.email", "test@alc.local")
    _git(repo, "config", "user.name", "ALC Test")
    (repo / "seed.txt").write_text("line-a\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    return repo


def _make_branch(repo: Path, branch: str) -> None:
    """Create *branch* at HEAD — liveness only cares that the ref exists."""
    _git(repo, "branch", branch)


# ---------------------------------------------------------------------------
# mark_live
# ---------------------------------------------------------------------------


class TestMarkLive:
    def test_marks_a_present_branch_live_and_a_gone_one_resolved(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/variant-1-aaaaaaaa")  # A still exists
        # B's branch was never created (adopted or discarded) — resolved.
        rows = [
            {"branch": "alc/variant-1-aaaaaaaa"},
            {"branch": "alc/variant-2-bbbbbbbb"},
        ]

        mark_live(rows, repo)

        assert rows[0]["live"] is True
        assert rows[1]["live"] is False

    def test_repo_root_none_marks_every_row_resolved(self, tmp_path: Path) -> None:
        # Off-git = no branches = nothing actionable = the safe default (no broken button).
        rows = [{"branch": "alc/variant-1-aaaaaaaa"}, {"branch": "alc/variant-2-bbbbbbbb"}]

        mark_live(rows, None)

        assert all(row["live"] is False for row in rows)

    def test_a_never_committed_row_is_resolved(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/variant-1-aaaaaaaa")
        rows = [{"branch": None}]  # a unit that never committed has no branch

        mark_live(rows, repo)

        assert rows[0]["live"] is False

    def test_returns_the_mutated_list(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        rows = [{"branch": "alc/variant-1-aaaaaaaa"}]

        result = mark_live(rows, repo)

        assert result is rows
        assert "live" in result[0]
