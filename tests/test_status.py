# test_status.py — Hermetic tests for `alc status`: aggregated health signals
# for external monitoring. Uses the conftest `operator_layer` fixture; branch
# counting uses a real LOCAL git repository, mirroring test_land.py/test_discard.py.
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import yaml

from alc.cli import cmd_status
from alc.intake import load_manifest
from alc.loop import loops_dir, save_loop_state, state_path
from alc.models import FlowReport, LoopState, QueueTask, RunReport, Scorecard


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


def _make_branch(repo: Path, branch: str, filename: str, content: str) -> None:
    _git(repo, "checkout", "-b", branch, "main")
    (repo / filename).write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", f"feat(auto): {branch}")
    _git(repo, "checkout", "main")


def _write_pending(operator_layer: Path, stem: str = "t1") -> None:
    manifest = load_manifest(operator_layer)
    queue_dir = operator_layer.parent / manifest.queue_dir
    queue_dir.mkdir(parents=True, exist_ok=True)
    qt = QueueTask(flow="ship", task="do the thing")
    (queue_dir / f"{stem}.yaml").write_text(yaml.safe_dump(qt.model_dump()))


def _write_failed_archive(operator_layer: Path, stem: str = "failed-1") -> None:
    manifest = load_manifest(operator_layer)
    done_dir = operator_layer.parent / manifest.queue_dir / "done"
    done_dir.mkdir(parents=True, exist_ok=True)
    qt = QueueTask(flow="ship", task="do the thing")
    (done_dir / f"{stem}.yaml").write_text(yaml.safe_dump(qt.model_dump()))
    failed_stage = RunReport(
        blueprint="chore",
        engine="mock",
        success=False,
        attempts=[],
        scorecard=Scorecard(span=0, passes=1, streak=0, touch=0),
        output_text="boom",
    )
    report = FlowReport(
        flow="ship",
        engine="mock",
        success=False,
        stages=[failed_stage],
        scorecard=Scorecard(span=0, passes=1, streak=0, touch=0),
    )
    (done_dir / f"{stem}.report.json").write_text(report.model_dump_json())


def _write_loop(
    operator_layer: Path,
    name: str,
    status: str = "pending",
    cycle: int = 0,
    stopped_reason: str | None = None,
) -> None:
    manifest = load_manifest(operator_layer)
    loops = loops_dir(manifest, operator_layer)
    loops.mkdir(parents=True, exist_ok=True)
    (loops / f"{name}.yaml").write_text(f"name: {name}\n")
    state = LoopState(name=name, status=status, cycle=cycle, stopped_reason=stopped_reason)
    save_loop_state(state_path(loops, name), state)


def _ns(**overrides) -> argparse.Namespace:
    defaults = {"json": False}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# Always exits 0, whatever it finds.
# ---------------------------------------------------------------------------


class TestStatusAlwaysExitsZero:
    def test_empty_project_exits_zero(self, operator_layer: Path, monkeypatch) -> None:
        monkeypatch.chdir(operator_layer.parent)
        assert cmd_status(_ns()) == 0

    def test_stopped_loop_still_exits_zero(self, operator_layer: Path, monkeypatch) -> None:
        _write_loop(operator_layer, "deliver", status="stopped", stopped_reason="max_cycles")
        monkeypatch.chdir(operator_layer.parent)
        assert cmd_status(_ns()) == 0


# ---------------------------------------------------------------------------
# Payload contents.
# ---------------------------------------------------------------------------


class TestStatusPayload:
    def test_pending_count(self, operator_layer: Path, monkeypatch, capsys) -> None:
        _write_pending(operator_layer, "t1")
        _write_pending(operator_layer, "t2")
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_status(_ns(json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["pending"] == 2

    def test_outstanding_failures_count(self, operator_layer: Path, monkeypatch, capsys) -> None:
        _write_failed_archive(operator_layer, "failed-1")
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_status(_ns(json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["outstanding_failures"] == 1

    def test_loops_surface_name_status_cycle_and_stopped_reason(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        _write_loop(operator_layer, "deliver", status="running", cycle=3)
        _write_loop(operator_layer, "cleanup", status="stopped", cycle=10, stopped_reason="budget")
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_status(_ns(json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        by_name = {loop["name"]: loop for loop in data["loops"]}
        assert by_name["deliver"] == {
            "name": "deliver",
            "status": "running",
            "cycle": 3,
            "stopped_reason": None,
        }
        assert by_name["cleanup"] == {
            "name": "cleanup",
            "status": "stopped",
            "cycle": 10,
            "stopped_reason": "budget",
        }

    def test_no_loops_dir_yields_empty_loops_list(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_status(_ns(json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["loops"] == []

    def test_unmerged_branch_count(self, operator_layer: Path, monkeypatch, capsys) -> None:
        repo = operator_layer.parent
        subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
        _git(repo, "config", "user.email", "test@alc.local")
        _git(repo, "config", "user.name", "ALC Test")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "init")
        _make_branch(repo, "alc/tick-aaaaaaaa", "a.txt", "a\n")
        monkeypatch.chdir(repo)

        assert cmd_status(_ns(json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["unmerged_branches"] == 1

    def test_zero_branches_outside_git_repo(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_status(_ns(json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["unmerged_branches"] == 0


# ---------------------------------------------------------------------------
# Human-readable output calls out a stopped loop.
# ---------------------------------------------------------------------------


class TestStatusHumanOutput:
    def test_stopped_loop_is_called_out(self, operator_layer: Path, monkeypatch, capsys) -> None:
        _write_loop(operator_layer, "cleanup", status="stopped", cycle=10, stopped_reason="budget")
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_status(_ns()) == 0
        out = capsys.readouterr().out
        assert "cleanup: stopped (cycle 10)" in out
        assert "stopped_reason=budget" in out

    def test_no_loops_prints_none(self, operator_layer: Path, monkeypatch, capsys) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_status(_ns()) == 0
        assert "(none)" in capsys.readouterr().out
