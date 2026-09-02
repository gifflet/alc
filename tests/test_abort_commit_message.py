# test_abort_commit_message.py — an aborted unwind must never wait on an engine.
#
# Dogfood finding 4: the UI's Cancel SIGKILLs
# after a grace period, and the worktree's exit-commit generated its message
# with an ENGINE call that takes longer than that — so the kill landed mid-
# generation, leaking the worktree and orphaning the engine's work. That broke,
# on the UI path only, the promise D2 makes everywhere: cancelling still
# commits your work to the branch.
from __future__ import annotations

import subprocess
from pathlib import Path

from alc.worktree import IsolatedWorktree


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    for argv in (
        ["git", "init", "-q", "."],
        ["git", "config", "user.email", "t@t"],
        ["git", "config", "user.name", "t"],
        ["git", "commit", "-q", "--allow-empty", "-m", "init"],
    ):
        subprocess.run(argv, cwd=repo, check=True, capture_output=True)
    return repo


class _Provider:
    """Stands in for the engine-backed commit-message provider."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, diff: str) -> str:
        self.calls += 1
        return "engine: authored message"


class TestAbortSkipsTheEngine:
    def test_an_aborted_exit_commits_with_the_static_message(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        provider = _Provider()
        wt = IsolatedWorktree(repo, label="run", message_provider=provider)
        path = wt.__enter__()
        (path / "work.txt").write_text("engine output\n")

        # Exactly how an interrupt unwinds through the context manager.
        wt.__exit__(KeyboardInterrupt, KeyboardInterrupt(), None)

        assert wt.committed is True
        assert provider.calls == 0, "the abort path must not wait on an engine"
        message = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%s", wt.branch],
            capture_output=True, text=True,
        ).stdout.strip()
        assert message == f"alc: {wt.branch}"

    def test_a_clean_exit_still_asks_the_provider(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        provider = _Provider()
        wt = IsolatedWorktree(repo, label="run", message_provider=provider)
        path = wt.__enter__()
        (path / "work.txt").write_text("engine output\n")

        wt.__exit__(None, None, None)

        assert wt.committed is True
        assert provider.calls == 1
        message = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%s", wt.branch],
            capture_output=True, text=True,
        ).stdout.strip()
        assert message == "engine: authored message"

    def test_the_aborted_worktree_is_removed_not_leaked(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        wt = IsolatedWorktree(repo, label="run", message_provider=_Provider())
        path = wt.__enter__()
        (path / "work.txt").write_text("x\n")

        wt.__exit__(KeyboardInterrupt, KeyboardInterrupt(), None)

        assert not path.exists()
        listing = subprocess.run(
            ["git", "-C", str(repo), "worktree", "list"], capture_output=True, text=True
        ).stdout
        assert str(path) not in listing

    def test_an_aborted_exit_with_no_changes_commits_nothing(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        provider = _Provider()
        wt = IsolatedWorktree(repo, label="run", message_provider=provider)
        wt.__enter__()

        wt.__exit__(KeyboardInterrupt, KeyboardInterrupt(), None)

        assert wt.committed is False
        assert provider.calls == 0


class TestUnprovisionedDepHint:
    """Dogfood finding 3: a missing provision must be named, not inferred from
    npx's stray-package errors three checks later."""

    @staticmethod
    def _node_repo(tmp_path: Path) -> Path:
        repo = _repo(tmp_path)
        (repo / "ui").mkdir()
        (repo / "ui" / "package.json").write_text('{"name":"ui"}')
        (repo / ".gitignore").write_text("node_modules/\n")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "node"], cwd=repo, check=True, capture_output=True)
        (repo / "ui" / "node_modules").mkdir()
        (repo / "ui" / "node_modules" / "x.js").write_text("x")
        return repo

    def test_names_the_gap_on_stderr(self, tmp_path: Path, capsys) -> None:
        repo = self._node_repo(tmp_path)
        wt = IsolatedWorktree(repo, label="run")
        wt.__enter__()
        err = capsys.readouterr().err

        assert "ui/node_modules exists in your project" in err
        assert "worktree_provision" in err
        wt.__exit__(None, None, None)

    def test_a_provisioned_dir_is_not_named(self, tmp_path: Path, capsys) -> None:
        from alc.models import ProvisionSpec

        repo = self._node_repo(tmp_path)
        wt = IsolatedWorktree(
            repo, label="run", provisions=[ProvisionSpec(clone="ui/node_modules")]
        )
        wt.__enter__()

        assert "[hint]" not in capsys.readouterr().err
        wt.__exit__(None, None, None)

    def test_a_project_without_node_stays_silent(self, tmp_path: Path, capsys) -> None:
        repo = _repo(tmp_path)
        wt = IsolatedWorktree(repo, label="run")
        wt.__enter__()

        assert "[hint]" not in capsys.readouterr().err
        wt.__exit__(None, None, None)
