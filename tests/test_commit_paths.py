# test_commit_paths.py — Hermetic tests for commit.commit_paths, the path-scoped
# sibling of commit_workdir.
#
# commit_paths exists so a caller that ran an agent IN-PLACE on the operator's own
# working tree can commit ONLY the run's own products — never the operator's
# pre-existing uncommitted work. Uses a real LOCAL git repo in tmp_path; no model
# and no network are ever needed.
from __future__ import annotations

import subprocess
from pathlib import Path

from alc.commit import commit_paths


# ---------------------------------------------------------------------------
# Git helpers (mirroring the _init_git_repo idiom used across the suite).
# ---------------------------------------------------------------------------


def _init_git_repo(repo: Path) -> None:
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@alc.local"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "ALC Test"],
        check=True,
        capture_output=True,
    )


def _commit_all(repo: Path, message: str) -> None:
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", message], check=True, capture_output=True
    )


def _build_repo(tmp_path: Path) -> Path:
    """A committed git repo with one tracked file (README.md)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / "README.md").write_text("seed\n")
    _commit_all(repo, "seed")
    return repo


def _committed_files(repo: Path) -> list[str]:
    """Files touched by the HEAD commit (git show --name-only)."""
    out = subprocess.run(
        ["git", "-C", str(repo), "show", "--name-only", "--format=", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return out.split()


def _status(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _ls_files(repo: Path) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(repo), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return out.splitlines()


def _rev_count(repo: Path) -> int:
    out = subprocess.run(
        ["git", "-C", str(repo), "rev-list", "--count", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return int(out.strip())


# ---------------------------------------------------------------------------
# The headline guarantee: only the listed paths land; WIP + cruft stay.
# ---------------------------------------------------------------------------


class TestCommitPaths:
    def test_commits_only_listed_paths_leaving_wip_and_cruft(self, tmp_path: Path) -> None:
        """Exactly the listed path is committed; a pre-existing modified tracked file
        AND an untracked cruft file NOT in the list stay uncommitted, contents intact."""
        repo = _build_repo(tmp_path)
        # A second tracked file the operator will then modify as WIP.
        (repo / "wip.py").write_text("original\n")
        _commit_all(repo, "add wip.py")

        # Operator WIP + cruft (neither listed), and the machine's own product.
        (repo / "wip.py").write_text("OPERATOR SENTINEL WIP\n")
        (repo / "cruft.log").write_text("scratch noise\n")
        (repo / "product.md").write_text("machine product\n")

        sha = commit_paths(repo, ["product.md"], "chore(auto): our product")

        assert sha is not None
        # Only our product is in the commit.
        assert _committed_files(repo) == ["product.md"]

        status = _status(repo)
        # The operator's tracked WIP is still modified (unstaged), sentinel intact.
        assert " M wip.py" in status
        assert (repo / "wip.py").read_text() == "OPERATOR SENTINEL WIP\n"
        # The untracked cruft is still untracked — never swept in.
        assert "?? cruft.log" in status

    def test_empty_list_returns_none_and_makes_no_commit(self, tmp_path: Path) -> None:
        repo = _build_repo(tmp_path)
        # Something dirty in the tree, but nothing listed.
        (repo / "dirty.txt").write_text("uncommitted\n")

        before = _rev_count(repo)
        assert commit_paths(repo, [], "chore(auto): nothing") is None
        assert _rev_count(repo) == before
        # The dirty file was never touched.
        assert "?? dirty.txt" in _status(repo)

    def test_alc_prefixed_entries_are_excluded(self, tmp_path: Path) -> None:
        repo = _build_repo(tmp_path)
        (repo / ".alc").mkdir()
        (repo / ".alc" / "state.json").write_text("control-plane state\n")
        (repo / "real.txt").write_text("real product\n")

        sha = commit_paths(repo, [".alc/state.json", "real.txt"], "chore(auto): x")

        assert sha is not None
        committed = _committed_files(repo)
        assert "real.txt" in committed
        assert ".alc/state.json" not in committed
        # The .alc entry stays uncommitted (protected). Porcelain collapses the
        # untracked directory to "?? .alc/".
        assert "?? .alc/" in _status(repo)
        assert ".alc/state.json" not in _ls_files(repo)

    def test_all_excluded_after_filter_returns_none(self, tmp_path: Path) -> None:
        repo = _build_repo(tmp_path)
        (repo / ".alc").mkdir()
        (repo / ".alc" / "state.json").write_text("state\n")

        before = _rev_count(repo)
        assert commit_paths(repo, [".alc/state.json"], "chore(auto): x") is None
        assert _rev_count(repo) == before

    def test_deletion_path_is_staged_and_committed(self, tmp_path: Path) -> None:
        repo = _build_repo(tmp_path)
        (repo / "goner.txt").write_text("bye\n")
        _commit_all(repo, "add goner")

        (repo / "goner.txt").unlink()
        sha = commit_paths(repo, ["goner.txt"], "chore(auto): remove goner")

        assert sha is not None
        # The deletion was committed: goner.txt is gone from the index and the tree is clean.
        assert "goner.txt" not in _ls_files(repo)
        assert "goner.txt" not in _status(repo)

    def test_non_repo_returns_none_without_crashing(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        (plain / "f.txt").write_text("x\n")
        assert commit_paths(plain, ["f.txt"], "chore(auto): x") is None

    def test_clean_path_in_list_makes_no_empty_commit(self, tmp_path: Path) -> None:
        repo = _build_repo(tmp_path)
        (repo / "tracked.txt").write_text("committed content\n")
        _commit_all(repo, "add tracked")

        before = _rev_count(repo)
        # tracked.txt is clean (unchanged); listing it must not create an empty commit.
        assert commit_paths(repo, ["tracked.txt"], "chore(auto): noop") is None
        assert _rev_count(repo) == before

    def test_rename_entry_normalizes_to_destination(self, tmp_path: Path) -> None:
        """A porcelain rename spelling 'old -> new' must normalize to its destination
        so the destination is staged (never passed verbatim as a bad pathspec)."""
        repo = _build_repo(tmp_path)
        (repo / "old.txt").write_text("content\n")
        _commit_all(repo, "add old")

        # Simulate a rename in the working tree.
        (repo / "old.txt").unlink()
        (repo / "new.txt").write_text("content\n")

        sha = commit_paths(repo, ["old.txt -> new.txt"], "chore(auto): rename")

        assert sha is not None, "rename entry must normalize to its destination and commit"
        assert "new.txt" in _committed_files(repo)
