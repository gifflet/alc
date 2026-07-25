# test_dirty_tree_guard.py — Preflight: an autonomous run (`alc cycle`, `alc loop`,
# `alc tick`) must refuse to START when the working tree carries uncommitted work
# OUTSIDE `.alc/`, so the run's demand-commit / merge-back never sweeps the
# operator's unrelated work-in-progress into a commit.
#
# Uses a real LOCAL git repo in tmp_path + monkeypatched engine/queue paths; no
# model is ever called and no real cycle ever runs.
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from alc.cli import _abort_if_dirty_tree
from alc.models import CycleRecord

# ---------------------------------------------------------------------------
# Inline operator layer + git helpers.
# ---------------------------------------------------------------------------

_MANIFEST = """\
version: 1
default_engine: mock
compute_tiers:
  standard:
    mock: mock-small
engines:
  mock:
    type: mock
blueprints_dir: .alc/blueprints
flows_dir: .alc/flows
queue_dir: .alc/queue
"""

_CHORE = """\
---
name: chore
purpose: Apply a low-risk, well-scoped maintenance change.
compute_tier: standard
checks:
  - name: smoke
    command: ["true"]
---
# Workflow
1. Make the smallest change that satisfies the task.
"""

_SHIP = """\
name: ship
description: Implement a change.
stages:
  - name: build
    blueprint: chore
"""

# Mode B (drain-only) loop: no replenish, so it validates without any refs.
_LOOP = """\
name: deliver
stop:
  max_cycles: 20
"""


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
    """Build a git repo with a committed operator layer (clean baseline)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    alc = repo / ".alc"
    (alc / "blueprints").mkdir(parents=True)
    (alc / "flows").mkdir(parents=True)
    (alc / "loops").mkdir(parents=True)
    (alc / "manifest.yaml").write_text(_MANIFEST)
    (alc / "blueprints" / "chore.md").write_text(_CHORE)
    (alc / "flows" / "ship.yaml").write_text(_SHIP)
    (alc / "loops" / "deliver.yaml").write_text(_LOOP)
    _commit_all(repo, "seed operator layer")
    return repo


def _fake_run_cycle(calls: list):
    """A run_cycle stand-in that records the call and stops the loop immediately."""

    def _run(manifest, operator_layer, loop_def, state, engine_override=None):
        calls.append(True)
        stopped = state.model_copy(
            update={
                "status": "stopped",
                "stopped_reason": "test-stop",
                "cycle": state.cycle + 1,
            }
        )
        record = CycleRecord(
            cycle=stopped.cycle,
            replenished=0,
            drained=0,
            succeeded=0,
            failed=0,
            progress=False,
            budget_delta={},
            stopped_reason="test-stop",
        )
        return stopped, record

    return _run


def _boom(*args, **kwargs):
    raise AssertionError("the autonomous run must not start on a dirty tree")


# ---------------------------------------------------------------------------
# Unit matrix: the shared guard helper.
# ---------------------------------------------------------------------------


class TestAbortIfDirtyTree:
    def test_dirty_non_alc_aborts(self, tmp_path: Path, capsys) -> None:
        repo = _build_repo(tmp_path)
        (repo / "wip.txt").write_text("unrelated work\n")

        assert _abort_if_dirty_tree(repo, allow_dirty=False, command="cycle") is True
        err = capsys.readouterr().err
        assert "cycle aborted" in err
        assert "--allow-dirty" in err

    def test_allow_dirty_bypasses(self, tmp_path: Path, capsys) -> None:
        repo = _build_repo(tmp_path)
        (repo / "wip.txt").write_text("unrelated work\n")

        assert _abort_if_dirty_tree(repo, allow_dirty=True, command="cycle") is False
        assert capsys.readouterr().err == ""

    def test_clean_tree_proceeds(self, tmp_path: Path) -> None:
        repo = _build_repo(tmp_path)
        assert _abort_if_dirty_tree(repo, allow_dirty=False, command="cycle") is False

    def test_alc_only_change_does_not_abort(self, tmp_path: Path) -> None:
        repo = _build_repo(tmp_path)
        # A change confined to .alc/ (control-plane state) must NOT block.
        (repo / ".alc" / "scratch.txt").write_text("state\n")
        assert _abort_if_dirty_tree(repo, allow_dirty=False, command="tick") is False

    def test_off_git_is_noop(self, tmp_path: Path) -> None:
        # tmp_path is not a git repo -> has_non_alc_changes is False -> no block.
        (tmp_path / "wip.txt").write_text("unrelated work\n")
        assert _abort_if_dirty_tree(tmp_path, allow_dirty=False, command="loop") is False

    def test_message_uses_command_label(self, tmp_path: Path, capsys) -> None:
        repo = _build_repo(tmp_path)
        (repo / "wip.txt").write_text("unrelated work\n")
        _abort_if_dirty_tree(repo, allow_dirty=False, command="tick")
        assert "tick aborted" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Integration: the guard is wired into each command entry.
# ---------------------------------------------------------------------------


class TestCmdCycleGuard:
    def test_aborts_on_dirty_tree(self, tmp_path: Path, monkeypatch, capsys) -> None:
        from alc.cli import cmd_cycle

        repo = _build_repo(tmp_path)
        (repo / "wip.txt").write_text("unrelated work\n")
        monkeypatch.chdir(repo)
        monkeypatch.setattr("alc.loop.run_cycle", _boom)

        args = argparse.Namespace(
            name="deliver", engine="mock", concurrency=0,
            status=False, reset=False, allow_dirty=False,
        )
        assert cmd_cycle(args) == 1
        err = capsys.readouterr().err
        assert "cycle aborted" in err
        assert "--allow-dirty" in err

    def test_proceeds_on_clean_tree(self, tmp_path: Path, monkeypatch) -> None:
        from alc.cli import cmd_cycle

        repo = _build_repo(tmp_path)
        monkeypatch.chdir(repo)
        calls: list = []
        monkeypatch.setattr("alc.loop.run_cycle", _fake_run_cycle(calls))

        args = argparse.Namespace(
            name="deliver", engine="mock", concurrency=0,
            status=False, reset=False, allow_dirty=False,
        )
        assert cmd_cycle(args) == 0
        assert calls == [True]

    def test_allow_dirty_proceeds_on_dirty_tree(self, tmp_path: Path, monkeypatch) -> None:
        from alc.cli import cmd_cycle

        repo = _build_repo(tmp_path)
        (repo / "wip.txt").write_text("unrelated work\n")
        monkeypatch.chdir(repo)
        calls: list = []
        monkeypatch.setattr("alc.loop.run_cycle", _fake_run_cycle(calls))

        args = argparse.Namespace(
            name="deliver", engine="mock", concurrency=0,
            status=False, reset=False, allow_dirty=True,
        )
        assert cmd_cycle(args) == 0
        assert calls == [True]


class TestCmdLoopGuard:
    def test_aborts_on_dirty_tree(self, tmp_path: Path, monkeypatch, capsys) -> None:
        from alc.cli import cmd_loop

        repo = _build_repo(tmp_path)
        (repo / "wip.txt").write_text("unrelated work\n")
        monkeypatch.chdir(repo)
        monkeypatch.setattr("alc.loop.run_cycle", _boom)

        args = argparse.Namespace(
            name="deliver", engine="mock", interval=0, reset=False, allow_dirty=False
        )
        assert cmd_loop(args) == 1
        err = capsys.readouterr().err
        assert "loop aborted" in err
        assert "--allow-dirty" in err

    def test_proceeds_on_clean_tree(self, tmp_path: Path, monkeypatch) -> None:
        from alc.cli import cmd_loop

        repo = _build_repo(tmp_path)
        monkeypatch.chdir(repo)
        calls: list = []
        monkeypatch.setattr("alc.loop.run_cycle", _fake_run_cycle(calls))

        args = argparse.Namespace(
            name="deliver", engine="mock", interval=0, reset=False, allow_dirty=False
        )
        assert cmd_loop(args) == 0
        assert calls == [True]

    def test_allow_dirty_proceeds_on_dirty_tree(self, tmp_path: Path, monkeypatch) -> None:
        from alc.cli import cmd_loop

        repo = _build_repo(tmp_path)
        (repo / "wip.txt").write_text("unrelated work\n")
        monkeypatch.chdir(repo)
        calls: list = []
        monkeypatch.setattr("alc.loop.run_cycle", _fake_run_cycle(calls))

        args = argparse.Namespace(
            name="deliver", engine="mock", interval=0, reset=False, allow_dirty=True
        )
        assert cmd_loop(args) == 0
        assert calls == [True]


class TestCmdTickGuard:
    def test_aborts_on_dirty_tree(self, tmp_path: Path, monkeypatch, capsys) -> None:
        from alc.cli import cmd_tick

        repo = _build_repo(tmp_path)
        (repo / "wip.txt").write_text("unrelated work\n")
        monkeypatch.chdir(repo)
        monkeypatch.setattr("alc.queue.process_queue", _boom)

        args = argparse.Namespace(concurrency=1, allow_dirty=False)
        assert cmd_tick(args) == 1
        err = capsys.readouterr().err
        assert "tick aborted" in err
        assert "--allow-dirty" in err

    def test_proceeds_on_clean_tree(self, tmp_path: Path, monkeypatch) -> None:
        from alc.cli import cmd_tick

        repo = _build_repo(tmp_path)
        # A queue dir under .alc/ must exist so the drain path is reached; it is
        # untracked but confined to .alc/, so the guard still treats the tree as clean.
        (repo / ".alc" / "queue").mkdir(parents=True, exist_ok=True)
        monkeypatch.chdir(repo)
        calls: list = []

        def _fake_process_queue(manifest, operator_layer, max_workers=1):
            calls.append(True)
            return []

        monkeypatch.setattr("alc.queue.process_queue", _fake_process_queue)

        args = argparse.Namespace(concurrency=1, allow_dirty=False)
        assert cmd_tick(args) == 0
        assert calls == [True]

    def test_allow_dirty_proceeds_on_dirty_tree(self, tmp_path: Path, monkeypatch) -> None:
        from alc.cli import cmd_tick

        repo = _build_repo(tmp_path)
        (repo / "wip.txt").write_text("unrelated work\n")
        (repo / ".alc" / "queue").mkdir(parents=True, exist_ok=True)
        monkeypatch.chdir(repo)
        calls: list = []

        def _fake_process_queue(manifest, operator_layer, max_workers=1):
            calls.append(True)
            return []

        monkeypatch.setattr("alc.queue.process_queue", _fake_process_queue)

        args = argparse.Namespace(concurrency=1, allow_dirty=True)
        assert cmd_tick(args) == 0
        assert calls == [True]
