# test_queue_run_kind.py — a Blueprint can be enqueued directly.
#
# Dogfood finding 8: `QueueTask.kind` was closed to flow|specialist, so queueing
# a chore-sized task — the first thing anyone drops in a queue — meant writing a
# one-stage wrapper flow by hand. `kind: run` is that wrapper moved inside the
# tool: dispatch builds a synthetic one-stage flow, so everything downstream
# (FlowReport, stages, archiving, Mix Health) keeps one shape.
#
# Also here: finding 9's other half at the drain — a successful committed tick
# branch archives a branch-named report, so the Inbox can say "verified" instead
# of shrugging None (see test_branch_verified.py for the reader side).
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from alc.branches import branch_verified, run_report_filename
from alc.intake import load_manifest
from alc.queue import process_queue

_RUN_TASK_YAML = """\
kind: run
name: chore
task: "tidy one thing"
engine: mock
isolate: false
"""


class TestRunKindDrains:
    def test_a_queued_blueprint_runs_and_archives(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "t1.yaml").write_text(_RUN_TASK_YAML)

        results = process_queue(manifest, operator_layer)

        assert len(results) == 1
        assert results[0].success is True
        report = json.loads((queue_dir / "done" / "t1.report.json").read_text())
        # The synthetic flow is named after the blueprint and has ONE stage.
        assert report["flow"] == "chore"
        assert len(report["stages"]) == 1

    def test_an_unknown_blueprint_fails_the_task_not_the_drain(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "t1.yaml").write_text(_RUN_TASK_YAML.replace("name: chore", "name: nosuch"))

        results = process_queue(manifest, operator_layer)

        assert len(results) == 1
        assert results[0].success is False


class TestEnqueueValidatesTheBlueprint:
    def test_enqueue_run_kind_checks_the_blueprint_exists(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        from alc.cli import cmd_enqueue

        monkeypatch.chdir(operator_layer.parent)
        ns = argparse.Namespace(
            kind="run", name="nosuch", task="x", engine=None, isolate=True,
            id=None, depends_on=[], touches=[], priority=0, from_file=None, json=False,
        )

        assert cmd_enqueue(ns) == 1
        assert "nosuch" in capsys.readouterr().err

    def test_enqueue_run_kind_accepts_a_real_blueprint(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        from alc.cli import cmd_enqueue

        monkeypatch.chdir(operator_layer.parent)
        ns = argparse.Namespace(
            kind="run", name="chore", task="tidy", engine=None, isolate=True,
            id=None, depends_on=[], touches=[], priority=0, from_file=None, json=False,
        )

        assert cmd_enqueue(ns) == 0


def _git_repo_layer(operator_layer: Path) -> Path:
    root = operator_layer.parent
    for argv in (
        ["git", "init", "-q", "."],
        ["git", "config", "user.email", "t@t"],
        ["git", "config", "user.name", "t"],
        ["git", "add", "-A"],
        ["git", "commit", "-qm", "init"],
    ):
        subprocess.run(argv, cwd=root, check=True, capture_output=True)
    return root


class _WritingMock:
    """A mock engine that writes a file, so the worktree has something to commit."""

    name = "mock"

    def capabilities(self):
        from alc.engine import Capabilities

        return Capabilities()

    def health_check(self) -> bool:
        return True

    def run(self, request):
        from alc.engine import EngineResult

        (request.workdir / "queued.txt").write_text("done\n")
        return EngineResult(ok=True, output_text="[mock] done")


class TestTickBranchesArchiveTheirReport:
    def test_a_passing_tick_branch_reads_verified(self, operator_layer: Path, monkeypatch) -> None:
        # Finding 9 end to end: drain an ISOLATED task that commits, then ask
        # the question the Inbox asks.
        root = _git_repo_layer(operator_layer)
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: _WritingMock())
        manifest = load_manifest(operator_layer)
        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "t1.yaml").write_text(_RUN_TASK_YAML.replace("isolate: false", "isolate: true"))
        monkeypatch.chdir(root)

        results = process_queue(manifest, operator_layer)

        assert results[0].success is True
        branch = results[0].branch
        assert branch is not None and branch.startswith("alc/tick-")
        runs_dir = operator_layer / "runs"
        assert (runs_dir / run_report_filename(branch)).exists()
        assert branch_verified(runs_dir, branch, "tick") is True

    def test_a_pre_upgrade_tick_branch_reads_unverified_not_none(self, tmp_path: Path) -> None:
        # Conservative on purpose: an old tick branch with no archived report
        # says "review before landing" rather than claiming either way silently.
        assert branch_verified(tmp_path, "alc/tick-old", "tick") is False

    def test_flow_and_fanout_still_shrug(self, tmp_path: Path) -> None:
        assert branch_verified(tmp_path, "alc/flow-x", "flow") is None
        assert branch_verified(tmp_path, "alc/fanout-x", "fanout-1") is None


class TestTheWriterKeepsTheKind:
    """The gap the live dogfood exposed: cmd_enqueue VALIDATED the blueprint but
    dispatch_enqueue rewrote the unit as `flow: chore`, which the drain then
    failed to load. These tests go through the writer, not hand-written YAML."""

    def test_an_enqueued_run_task_file_carries_the_kind(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        import yaml as _yaml

        from alc.cli import cmd_enqueue

        monkeypatch.chdir(operator_layer.parent)
        ns = argparse.Namespace(
            kind="run", name="chore", task="tidy", engine=None, isolate=False,
            id=None, depends_on=[], touches=[], priority=0, from_file=None, json=False,
        )
        assert cmd_enqueue(ns) == 0

        task_file = next((operator_layer / "queue").glob("*.yaml"))
        data = _yaml.safe_load(task_file.read_text())
        assert data.get("kind") == "run"
        assert data.get("name") == "chore"
        assert "flow" not in data or not data["flow"]

    def test_enqueue_then_drain_round_trips(self, operator_layer: Path, monkeypatch) -> None:
        from alc.cli import cmd_enqueue

        monkeypatch.chdir(operator_layer.parent)
        ns = argparse.Namespace(
            kind="run", name="chore", task="tidy", engine="mock", isolate=False,
            id=None, depends_on=[], touches=[], priority=0, from_file=None, json=False,
        )
        assert cmd_enqueue(ns) == 0

        manifest = load_manifest(operator_layer)
        results = process_queue(manifest, operator_layer)

        assert len(results) == 1
        assert results[0].success is True
