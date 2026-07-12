# test_merge.py — Hermetic tests for the Part D auto-merge pass.
# Uses a real LOCAL git repository created in tmp_path; no model is called. Demand
# branches are built off main with `git branch` + commit plumbing (no worktree needed).
from __future__ import annotations

import subprocess
from pathlib import Path

from alc.merge import MergeReport, auto_merge_branches


# ---------------------------------------------------------------------------
# Inline git helpers — mirror the house style (test_worktree.py / test_part_d.py).
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command against *repo*, returning the completed process."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )


def _make_git_repo(base: Path) -> Path:
    """Initialize a git repo with one seed commit on main and return its path."""
    repo = base / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.email", "test@alc.local")
    _git(repo, "config", "user.name", "ALC Test")
    (repo / "seed.txt").write_text("line-a\nline-b\nline-c\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    return repo


def _make_branch(repo: Path, branch: str, filename: str, content: str, subject: str) -> None:
    """Create *branch* off main, write *content* to *filename*, commit with *subject*.

    Leaves main checked out afterwards so the next branch is cut from the same base.
    """
    _git(repo, "checkout", "-b", branch, "main")
    (repo / filename).write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", subject)
    _git(repo, "checkout", "main")


def _branch_exists(repo: Path, branch: str) -> bool:
    """Return True if *branch* is present in the repo's branch list."""
    result = _git(repo, "branch", "--list", branch)
    return result.stdout.strip() != ""


def _head_subject(repo: Path) -> str:
    """Return the subject line of the current HEAD commit."""
    return _git(repo, "log", "-1", "--format=%s", "HEAD").stdout.strip()


def _main_content(repo: Path, filename: str) -> str:
    """Return the working-tree content of *filename* on the checked-out main."""
    return (repo / filename).read_text()


def _merge_in_progress(repo: Path) -> bool:
    """Return True if an integration is mid-flight (a merge OR cherry-pick in progress)."""
    git = repo / ".git"
    return (git / "MERGE_HEAD").exists() or (git / "CHERRY_PICK_HEAD").exists()


# ---------------------------------------------------------------------------
# D1 — the PRD case: two independent merge, one conflicting is left.
# ---------------------------------------------------------------------------


class TestAutoMergePrdCase:
    def test_two_independent_merge_one_conflict_left(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)

        # tick-aaa is fully INDEPENDENT (its own disjoint file).
        _make_branch(
            repo, "alc/tick-aaa", "feature_a.txt", "alpha\n", "feat(auto): add A"
        )
        # tick-bbb adds its own file AND rewrites seed.txt line 1. It still merges
        # cleanly (main's seed.txt line 1 is untouched at that point).
        _git(repo, "checkout", "-b", "alc/tick-bbb", "main")
        (repo / "feature_b.txt").write_text("beta\n")
        (repo / "seed.txt").write_text("line-a-from-B\nline-b\nline-c\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "feat(auto): add B")
        _git(repo, "checkout", "main")

        # tick-ccc edits the SAME seed.txt line 1 differently -> once tick-bbb is on
        # main, this branch conflicts on that line.
        _make_branch(
            repo,
            "alc/tick-ccc",
            "seed.txt",
            "line-a-from-C\nline-b\nline-c\n",
            "feat(auto): change C",
        )

        # Pass branches OUT of sorted order to also confirm the pass sorts them.
        report = auto_merge_branches(
            repo, ["alc/tick-ccc", "alc/tick-aaa", "alc/tick-bbb"]
        )

        # aaa + bbb merge (in sorted order); ccc conflicts.
        assert report.merged == ["alc/tick-aaa", "alc/tick-bbb"]
        assert report.conflicted == ["alc/tick-ccc"]

        # Merged branches are deleted; the conflicting one still exists.
        assert not _branch_exists(repo, "alc/tick-aaa")
        assert not _branch_exists(repo, "alc/tick-bbb")
        assert _branch_exists(repo, "alc/tick-ccc")

        # main's HEAD contains both independent changes.
        assert _main_content(repo, "feature_a.txt") == "alpha\n"
        assert _main_content(repo, "feature_b.txt") == "beta\n"

        # No merge left in progress — proves `git merge --abort` ran after the conflict.
        assert not _merge_in_progress(repo)
        assert "MERGING" not in _git(repo, "status").stdout


# ---------------------------------------------------------------------------
# D2 — all-independent branches merge and are deleted; conflicted empty.
# ---------------------------------------------------------------------------


class TestAutoMergeAllIndependent:
    def test_all_merge_and_are_deleted(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/tick-111", "a.txt", "a\n", "feat(auto): a")
        _make_branch(repo, "alc/tick-222", "b.txt", "b\n", "feat(auto): b")
        _make_branch(repo, "alc/tick-333", "c.txt", "c\n", "feat(auto): c")

        report = auto_merge_branches(
            repo, ["alc/tick-111", "alc/tick-222", "alc/tick-333"]
        )

        assert report.merged == ["alc/tick-111", "alc/tick-222", "alc/tick-333"]
        assert report.conflicted == []
        for branch in ("alc/tick-111", "alc/tick-222", "alc/tick-333"):
            assert not _branch_exists(repo, branch)
        # All three files landed on main.
        assert _main_content(repo, "a.txt") == "a\n"
        assert _main_content(repo, "b.txt") == "b\n"
        assert _main_content(repo, "c.txt") == "c\n"


# ---------------------------------------------------------------------------
# D3 — empty branches list -> empty report, repo untouched.
# ---------------------------------------------------------------------------


class TestAutoMergeEmpty:
    def test_empty_list_is_noop(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        head_before = _git(repo, "rev-parse", "HEAD").stdout.strip()

        report = auto_merge_branches(repo, [])

        assert report.merged == []
        assert report.conflicted == []
        # Repo HEAD is unchanged.
        assert _git(repo, "rev-parse", "HEAD").stdout.strip() == head_before


# ---------------------------------------------------------------------------
# D4 — the demand's OWN commit (message preserved) lands on the current branch.
# ---------------------------------------------------------------------------


class TestAutoMergeMessage:
    def test_head_subject_is_the_demand_commit_subject(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(
            repo, "alc/tick-msg", "x.txt", "x\n", "feat(auto): ship the feature"
        )

        report = auto_merge_branches(repo, ["alc/tick-msg"])

        assert report.merged == ["alc/tick-msg"]
        # Cherry-pick replays the demand's OWN commit onto HEAD, message preserved
        # (no merge commit reusing the subject).
        assert _head_subject(repo) == "feat(auto): ship the feature"


# ---------------------------------------------------------------------------
# D6 — integration is LINEAR: no merge commits, each demand appears exactly once.
# ---------------------------------------------------------------------------


class TestAutoMergeLinear:
    def test_no_merge_commits_and_no_duplicate_subjects(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/tick-a", "a.txt", "a\n", "feat(auto): add A")
        _make_branch(repo, "alc/tick-b", "b.txt", "b\n", "feat(auto): add B")

        report = auto_merge_branches(repo, ["alc/tick-a", "alc/tick-b"])
        assert report.merged == ["alc/tick-a", "alc/tick-b"]

        # No merge commit was created (the old --no-ff made one per demand).
        assert _git(repo, "log", "--merges", "--oneline").stdout.strip() == ""
        # Each demand's subject appears EXACTLY ONCE on the current branch — the old
        # approach showed it twice (the work commit + a merge commit reusing it).
        subjects = _git(repo, "log", "--format=%s").stdout.splitlines()
        assert subjects.count("feat(auto): add A") == 1
        assert subjects.count("feat(auto): add B") == 1


# ---------------------------------------------------------------------------
# D5 — merges are serialized/stable: merged list is always in sorted() order.
# ---------------------------------------------------------------------------


class TestAutoMergeStableOrder:
    def test_merged_list_is_sorted_regardless_of_input_order(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/tick-a", "a.txt", "a\n", "feat(auto): a")
        _make_branch(repo, "alc/tick-b", "b.txt", "b\n", "feat(auto): b")
        _make_branch(repo, "alc/tick-c", "c.txt", "c\n", "feat(auto): c")

        # Deliberately scrambled input order.
        report = auto_merge_branches(
            repo, ["alc/tick-c", "alc/tick-a", "alc/tick-b"]
        )

        assert report.merged == ["alc/tick-a", "alc/tick-b", "alc/tick-c"]


# ---------------------------------------------------------------------------
# summary() helper — the human-readable line printed by the caller.
# ---------------------------------------------------------------------------


class TestMergeReportSummary:
    def test_summary_with_conflicts_lists_branch_names(self) -> None:
        report = MergeReport(
            merged=["alc/tick-a", "alc/tick-b"], conflicted=["alc/tick-c"]
        )
        assert report.summary() == (
            "auto-merge: merged 2, left 1 for manual resolution (alc/tick-c)"
        )

    def test_summary_without_conflicts_omits_parenthetical(self) -> None:
        report = MergeReport(merged=["alc/tick-a"], conflicted=[])
        assert report.summary() == "auto-merge: merged 1, left 0 for manual resolution"
