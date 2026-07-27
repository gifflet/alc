# test_repostatus.py — The UI repo-status read model (repostatus.py).
#
# Split the same way watch.py is: parse_repo_status() is a PURE text->RepoStatus
# function covered with literal porcelain-v2 fixtures (no git), and repo_status()
# is exercised against throwaway git repos built in tmp (init/commit/local-remote
# there — NEVER a fetch, never the caller's working tree). The AGREEMENT test
# pins repo_status(root).dirty to commit.has_non_alc_changes(root): the UI read
# model must never disagree with the CLI/flow safety predicate on "dirty".
from __future__ import annotations

import subprocess
from pathlib import Path

from alc.commit import has_non_alc_changes
from alc.ui.repostatus import RepoStatus, parse_repo_status, repo_status


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _git_init(repo: Path) -> None:
    """Turn a directory into a git repo with one seed commit (clean tree after)."""
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.email", "test@alc.local")
    _git(repo, "config", "user.name", "ALC Test")
    (repo / "seed.txt").write_text("seed\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")


def _local_remote(repo: Path, remote_dir: Path) -> None:
    """Give *repo* a LOCAL bare remote and push main -u (sets upstream, no network)."""
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote_dir)],
        check=True,
        capture_output=True,
    )
    _git(repo, "remote", "add", "origin", str(remote_dir))
    _git(repo, "push", "-u", "origin", "main")


# ---------------------------------------------------------------------------
# parse_repo_status — PURE (text -> RepoStatus), literal porcelain-v2 fixtures
# ---------------------------------------------------------------------------


class TestParseRepoStatus:
    def test_empty_text_is_the_available_default(self) -> None:
        # A parsed status is always available=True (we only parse when git spoke);
        # everything else is the clean/in-git-repo default.
        assert parse_repo_status("") == RepoStatus(available=True)

    def test_clean_in_sync(self) -> None:
        text = (
            "# branch.oid abc123\n"
            "# branch.head main\n"
            "# branch.upstream origin/main\n"
            "# branch.ab +0 -0\n"
        )
        status = parse_repo_status(text)
        assert status == RepoStatus(
            available=True,
            dirty=False,
            branch="main",
            upstream="origin/main",
            ahead=0,
            behind=0,
            untracked=0,
        )

    def test_ahead_and_behind(self) -> None:
        text = (
            "# branch.oid abc123\n"
            "# branch.head main\n"
            "# branch.upstream origin/main\n"
            "# branch.ab +3 -2\n"
        )
        status = parse_repo_status(text)
        assert status.ahead == 3
        assert status.behind == 2
        assert status.upstream == "origin/main"

    def test_detached_head(self) -> None:
        text = "# branch.oid abc123\n# branch.head (detached)\n"
        status = parse_repo_status(text)
        assert status.detached is True
        assert status.branch is None

    def test_no_upstream_leaves_ahead_behind_none_not_zero(self) -> None:
        # A branch with no upstream has NO branch.ab line — ahead/behind must be
        # None (unknown), never 0 (which would falsely read as "in sync").
        text = "# branch.oid abc123\n# branch.head feature\n"
        status = parse_repo_status(text)
        assert status.branch == "feature"
        assert status.upstream is None
        assert status.ahead is None
        assert status.behind is None

    def test_upstream_set_but_no_ab(self) -> None:
        # Upstream configured but its tracking ref is gone (git omits branch.ab):
        # upstream is known, ahead/behind are not. Parsing them is DECOUPLED.
        text = (
            "# branch.oid abc123\n"
            "# branch.head main\n"
            "# branch.upstream origin/main\n"
        )
        status = parse_repo_status(text)
        assert status.upstream == "origin/main"
        assert status.ahead is None
        assert status.behind is None

    def test_unborn_initial_branch(self) -> None:
        # A fresh repo with no commits: branch.oid is (initial), branch.head still
        # carries the branch name. No ab line -> ahead/behind None.
        text = "# branch.oid (initial)\n# branch.head main\n"
        status = parse_repo_status(text)
        assert status.branch == "main"
        assert status.detached is False
        assert status.ahead is None

    def test_ordinary_change_outside_alc_is_dirty(self) -> None:
        text = (
            "# branch.head main\n"
            "1 .M N... 100644 100644 100644 aaaa bbbb src/app.py\n"
        )
        assert parse_repo_status(text).dirty is True

    def test_ordinary_change_only_inside_alc_is_not_dirty(self) -> None:
        text = (
            "# branch.head main\n"
            "1 .M N... 100644 100644 100644 aaaa bbbb .alc/loops/deliver.state.json\n"
        )
        status = parse_repo_status(text)
        assert status.dirty is False
        assert status.untracked == 0

    def test_untracked_mixed_alc_and_real_counts_only_real(self) -> None:
        text = (
            "# branch.head main\n"
            "? .alc/scratch.txt\n"
            "? b.txt\n"
            "? docs/notes.md\n"
        )
        status = parse_repo_status(text)
        assert status.dirty is True
        assert status.untracked == 2  # b.txt + docs/notes.md; the .alc one is excluded

    def test_collapsed_untracked_alc_dir_is_excluded(self) -> None:
        # git collapses a fully-untracked dir to a single trailing-slash entry.
        text = "# branch.head main\n? .alc/\n"
        status = parse_repo_status(text)
        assert status.dirty is False
        assert status.untracked == 0

    def test_rename_target_path_decides(self) -> None:
        # A type-2 line lists the TARGET path first, then \t<orig>. The dirty
        # decision uses the target: orig under .alc/ must not mask a real target.
        text = (
            "# branch.head main\n"
            "2 R. N... 100644 100644 100644 aaaa bbbb R100 real.txt\t.alc/old.txt\n"
        )
        assert parse_repo_status(text).dirty is True

    def test_rename_target_inside_alc_is_not_dirty(self) -> None:
        text = (
            "# branch.head main\n"
            "2 R. N... 100644 100644 100644 aaaa bbbb R100 .alc/new.txt\treal.txt\n"
        )
        assert parse_repo_status(text).dirty is False

    def test_unmerged_entry_is_dirty(self) -> None:
        text = (
            "# branch.head main\n"
            "u UU N... 100644 100644 100644 100644 aaaa bbbb cccc conflict.txt\n"
        )
        assert parse_repo_status(text).dirty is True

    def test_spaces_in_path_survive(self) -> None:
        text = (
            "# branch.head main\n"
            "1 .M N... 100644 100644 100644 aaaa bbbb my report.txt\n"
        )
        assert parse_repo_status(text).dirty is True

    def test_ignored_entries_are_skipped(self) -> None:
        # `!` ignored entries never count (defensive — they only appear with
        # --ignored, which we do not pass).
        text = "# branch.head main\n! build/output.js\n"
        status = parse_repo_status(text)
        assert status.dirty is False
        assert status.untracked == 0


# ---------------------------------------------------------------------------
# repo_status — the thin subprocess runner over throwaway repos
# ---------------------------------------------------------------------------


class TestRepoStatus:
    def test_off_git_is_unavailable(self, tmp_path: Path) -> None:
        # A plain directory (no git repo) degrades to available=False, never raises.
        status = repo_status(tmp_path)
        assert status == RepoStatus(available=False)

    def test_no_upstream_leaves_nones(self, tmp_path: Path) -> None:
        repo = tmp_path / "solo"
        _git_init(repo)
        status = repo_status(repo)
        assert status.available is True
        assert status.branch == "main"
        assert status.upstream is None
        assert status.ahead is None
        assert status.behind is None
        assert status.dirty is False

    def test_local_remote_ahead_by_one(self, tmp_path: Path) -> None:
        repo = tmp_path / "wc"
        _git_init(repo)
        _local_remote(repo, tmp_path / "rem.git")
        # One local commit that is NOT pushed -> ahead=1 read straight off the
        # local tracking ref (as of the push). We NEVER fetch to learn this.
        (repo / "more.txt").write_text("more\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "more")

        status = repo_status(repo)
        assert status.available is True
        assert status.branch == "main"
        assert status.upstream == "origin/main"
        assert status.ahead == 1
        assert status.behind == 0
        assert status.untracked == 0
        assert status.dirty is False

    def test_untracked_and_dirty_reflected(self, tmp_path: Path) -> None:
        repo = tmp_path / "wc"
        _git_init(repo)
        (repo / "wip.py").write_text("print('wip')\n")  # untracked, outside .alc/
        status = repo_status(repo)
        assert status.dirty is True
        assert status.untracked == 1


# ---------------------------------------------------------------------------
# The AGREEMENT test — repo_status(root).dirty MUST equal has_non_alc_changes(root)
# for every scenario. This is the contract that lets the UI read model and the
# CLI/flow safety predicate share one meaning of "dirty".
# ---------------------------------------------------------------------------


class TestDirtyAgreesWithHasNonAlcChanges:
    def _assert_agree(self, root: Path) -> None:
        assert repo_status(root).dirty == has_non_alc_changes(root)

    def test_clean_tree(self, tmp_path: Path) -> None:
        repo = tmp_path / "r"
        _git_init(repo)
        self._assert_agree(repo)

    def test_dirty_non_alc(self, tmp_path: Path) -> None:
        repo = tmp_path / "r"
        _git_init(repo)
        (repo / "src.py").write_text("print('wip')\n")
        self._assert_agree(repo)

    def test_alc_only_dirty(self, tmp_path: Path) -> None:
        repo = tmp_path / "r"
        _git_init(repo)
        (repo / ".alc").mkdir()
        (repo / ".alc" / "scratch.txt").write_text("control-plane churn\n")
        self._assert_agree(repo)

    def test_untracked_only(self, tmp_path: Path) -> None:
        repo = tmp_path / "r"
        _git_init(repo)
        (repo / "new.txt").write_text("brand new\n")
        self._assert_agree(repo)

    def test_off_git(self, tmp_path: Path) -> None:
        # Not a git repo: both degrade to "not dirty" (repo_status via
        # available=False -> dirty=False; the predicate via no-repo -> False).
        self._assert_agree(tmp_path)
