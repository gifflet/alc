# test_worktree.py — Hermetic tests for worktree isolation helpers.
# Uses a real LOCAL git repository created in tmp_path; no model is called.
from __future__ import annotations

import subprocess
from pathlib import Path


from alc.models import ProvisionSpec
from alc.worktree import IsolatedWorktree, is_git_repo, materialize_isolated


# ---------------------------------------------------------------------------
# Inline helper: create a minimal git repo in a temp directory.
# ---------------------------------------------------------------------------


def _make_git_repo(base: Path) -> Path:
    """Initialize a git repo with one commit inside *base* and return its path."""
    repo = base / "repo"
    repo.mkdir()
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
    (repo / "seed.txt").write_text("initial content\n")
    subprocess.run(
        ["git", "-C", str(repo), "add", "-A"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "init"],
        check=True,
        capture_output=True,
    )
    return repo


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestIsGitRepo:
    def test_true_inside_repo(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        assert is_git_repo(repo) is True

    def test_false_outside_repo(self, tmp_path: Path) -> None:
        non_repo = tmp_path / "not-a-repo"
        non_repo.mkdir()
        assert is_git_repo(non_repo) is False


class TestIsolatedWorktreeContainsEdits:
    def test_edits_stay_in_worktree_and_are_committed(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        wt_obj = IsolatedWorktree(repo, "test")

        with wt_obj as wt:
            # Write a new file inside the worktree.
            new_file = wt / "agent_output.txt"
            new_file.write_text("agent wrote this\n")

            # The file must NOT be visible in the main repo working tree.
            assert not (repo / "agent_output.txt").exists()

        # After exit: committed=True, worktree dir is gone, branch has the file.
        assert wt_obj.committed is True
        assert not wt_obj.path.exists()

        ls_result = subprocess.run(
            ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", wt_obj.branch],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "agent_output.txt" in ls_result.stdout

        # Clean up the leftover branch so the repo stays tidy.
        subprocess.run(
            ["git", "-C", str(repo), "branch", "-D", wt_obj.branch],
            capture_output=True,
        )


def _add_gitignored_node_modules(repo: Path) -> None:
    """Add a gitignored ``node_modules/`` dir (untracked) to *repo* and commit the
    .gitignore. A fresh worktree checks out only tracked files, so node_modules is
    absent there unless provisioning links/copies it in."""
    (repo / ".gitignore").write_text("node_modules/\n")
    (repo / "node_modules" / "pkg").mkdir(parents=True)
    (repo / "node_modules" / "pkg" / "index.js").write_text("module\n")
    subprocess.run(
        ["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "gitignore node_modules"],
        check=True,
        capture_output=True,
    )


class TestIsolatedWorktreeProvisions:
    """Part A: provisioning is centralised in ``__enter__`` so EVERY isolated path
    provisions identically (before this, `alc run --isolate` never provisioned)."""

    def test_provisions_are_linked_in_on_enter(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        _add_gitignored_node_modules(repo)
        wt_obj = IsolatedWorktree(
            repo, "test", provisions=[ProvisionSpec(link="node_modules")]
        )
        with wt_obj as wt:
            dep = wt / "node_modules"
            # A fresh worktree omits the gitignored dir; provisioning links it in.
            assert dep.is_symlink()
            assert dep.resolve() == (repo / "node_modules").resolve()

    def test_empty_provisions_leaves_the_worktree_bare(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        _add_gitignored_node_modules(repo)
        wt_obj = IsolatedWorktree(repo, "test")  # no provisions -> no-op
        with wt_obj as wt:
            # Byte-identical to today: nothing provisioned, so the gitignored dep
            # is simply absent from the fresh worktree.
            assert not (wt / "node_modules").exists()


class TestMaterializeIsolated:
    """`materialize_isolated` replaces a symlinked provision with an ISOLATED clone
    so a mutating refresh (npm install) can never write through the link into the
    operator's shared dependency dir."""

    def test_symlink_becomes_isolated_clone(self, tmp_path: Path) -> None:
        # Operator's shared dep dir with a marker file.
        source = tmp_path / "node_modules"
        (source / "pkg").mkdir(parents=True)
        (source / "pkg" / "lib.txt").write_text("oldAPI\n")

        # A worktree carrying node_modules as a SYMLINK to the operator's dir.
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        dst = worktree / "node_modules"
        dst.symlink_to(source)
        assert dst.is_symlink()

        materialize_isolated(dst)

        # dst is now a real directory (an isolated clone), not a symlink.
        assert dst.is_dir() and not dst.is_symlink()
        assert (dst / "pkg" / "lib.txt").read_text() == "oldAPI\n"

        # Writing into the clone does NOT touch the operator's source (the whole point).
        (dst / "pkg" / "lib.txt").write_text("newAPI\n")
        assert (source / "pkg" / "lib.txt").read_text() == "oldAPI\n"

    def test_dangling_target_leaves_dst_absent_no_crash(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        dst = worktree / "node_modules"
        # A symlink whose target does not exist (dangling).
        dst.symlink_to(tmp_path / "does-not-exist")

        materialize_isolated(dst)  # must not raise

        # The dangling link is gone; nothing was materialized (the install
        # creates it fresh).
        assert not dst.exists()
        assert not dst.is_symlink()

    def test_non_symlink_dst_is_left_untouched(self, tmp_path: Path) -> None:
        # Callers guard on is_symlink, but the helper must be safe if called on a
        # copy:/clone: dst (already isolated) — it leaves it exactly as is.
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        dst = worktree / "node_modules"
        (dst / "pkg").mkdir(parents=True)
        (dst / "pkg" / "lib.txt").write_text("copy\n")

        materialize_isolated(dst)

        assert dst.is_dir() and not dst.is_symlink()
        assert (dst / "pkg" / "lib.txt").read_text() == "copy\n"


class TestIsolatedWorktreeNoChangesCleanup:
    def test_no_changes_removes_worktree_and_branch(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        wt_obj = IsolatedWorktree(repo, "test")

        with wt_obj:
            # Write nothing — the body is intentionally empty.
            pass

        # After exit: not committed, worktree dir gone, branch deleted.
        assert wt_obj.committed is False
        assert not wt_obj.path.exists()

        branch_list = subprocess.run(
            ["git", "-C", str(repo), "branch", "--list", wt_obj.branch],
            capture_output=True,
            text=True,
            check=True,
        )
        assert branch_list.stdout.strip() == ""
