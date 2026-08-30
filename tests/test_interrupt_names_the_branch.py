# test_interrupt_names_the_branch.py — stopping an isolated run still commits.
#
# E2E finding 20. Ctrl-C during `alc run --isolate` unwinds through the
# worktree's __exit__, which COMMITS whatever the engine had already written onto
# the run branch and removes the worktree. The CLI then re-raised, so the operator
# got a twenty-line traceback and no mention of the branch — work existed in the
# repository that nothing had told them about, waiting to be met later by
# `alc land` with no record of where it came from.
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from alc.cli import _print_isolation_result, main


class _Worktree:
    """The two fields `_print_isolation_result` reads off a real worktree."""

    def __init__(self, committed: bool, branch: str = "alc/run-ce2f8479") -> None:
        self.committed = committed
        self.branch = branch
        self._repo_root = Path("/repo")


class TestTheIsolationResultIsPrintable:
    def test_a_committed_worktree_names_its_branch(self, capsys) -> None:
        _print_isolation_result(_Worktree(committed=True))
        out = capsys.readouterr().out

        assert "alc/run-ce2f8479" in out
        assert "review and merge" in out

    def test_an_empty_worktree_says_so(self, capsys) -> None:
        _print_isolation_result(_Worktree(committed=False))

        assert "No changes were made" in capsys.readouterr().out


class TestCtrlCIsNotACrash:
    def test_it_exits_130_with_one_line_and_no_traceback(self, monkeypatch, capsys) -> None:
        # 130 is the shell convention for a process ended by SIGINT.
        def _boom() -> None:
            raise KeyboardInterrupt

        monkeypatch.setattr("alc.cli._dispatch", _boom)
        with pytest.raises(SystemExit) as exit_info:
            main()

        assert exit_info.value.code == 130
        err = capsys.readouterr().err
        assert "Interrupted." in err
        assert "Traceback" not in err

    def test_a_normal_exit_code_still_passes_through(self, monkeypatch) -> None:
        def _ok() -> None:
            raise SystemExit(3)

        monkeypatch.setattr("alc.cli._dispatch", _ok)
        with pytest.raises(SystemExit) as exit_info:
            main()

        assert exit_info.value.code == 3


class TestTheBranchSurvivesAnInterruptedIsolatedRun:
    """The end-to-end fact the copy on both surfaces now depends on."""

    def test_worktree_exit_commits_what_the_engine_wrote(self, tmp_path: Path) -> None:
        from alc.worktree import IsolatedWorktree

        repo = tmp_path / "repo"
        repo.mkdir()
        for argv in (
            ["git", "init", "-q", "."],
            ["git", "config", "user.email", "t@t"],
            ["git", "config", "user.name", "t"],
            ["git", "commit", "-q", "--allow-empty", "-m", "init"],
        ):
            subprocess.run(argv, cwd=repo, check=True, capture_output=True)

        wt = IsolatedWorktree(repo_root=repo, label="run")
        path = wt.__enter__()
        (path / "abort-me.txt").write_text("x\n")
        # Unwinding on an interrupt passes the exception through __exit__ exactly
        # like this — and it commits anyway.
        wt.__exit__(KeyboardInterrupt, KeyboardInterrupt(), None)

        assert wt.committed is True
        listed = subprocess.run(
            ["git", "branch", "--list", wt.branch], cwd=repo, capture_output=True, text=True
        )
        assert wt.branch in listed.stdout
        # And NOT in the working tree the UI used to point at.
        assert not (repo / "abort-me.txt").exists()
