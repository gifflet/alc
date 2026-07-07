# test_fanout.py — Hermetic tests for concurrent fan-out.
# Uses a real LOCAL git repo in tmp_path + the Mock engine; no model is called.
from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import pytest

from alc.fanout import run_fanout, run_unit
from alc.intake import load_manifest
from alc.queue import process_queue
from alc.worktree import IsolatedWorktree


# ---------------------------------------------------------------------------
# Inline helpers.
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
1. Make the smallest change that satisfies the task; keep it single-purpose.
"""


def _init_git_repo(repo: Path) -> None:
    """Initialize a git repo with committed identity config inside *repo*."""
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


def _make_alc_repo(base: Path) -> Path:
    """Build a git repo containing a minimal .alc Operator Layer and return its root."""
    repo = base / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    alc = repo / ".alc"
    (alc / "blueprints").mkdir(parents=True)
    (alc / "flows").mkdir(parents=True)
    (alc / "manifest.yaml").write_text(_MANIFEST)
    (alc / "blueprints" / "chore.md").write_text(_CHORE)

    _commit_all(repo, "seed operator layer")
    return repo


def _branches(repo: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), "branch", "--format=%(refname:short)"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [b.strip() for b in result.stdout.splitlines() if b.strip()]


# ---------------------------------------------------------------------------
# (a) Worktree safety under concurrency.
# ---------------------------------------------------------------------------


class TestConcurrentWorktreeSafety:
    def test_four_threads_isolate_their_edits(self, tmp_path: Path) -> None:
        """Four concurrent worktrees each commit only their own unique file."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        (repo / "seed.txt").write_text("initial content\n")
        _commit_all(repo, "init")

        branches: dict[int, str] = {}
        barrier = threading.Barrier(4)

        def worker(index: int) -> None:
            wt_obj = IsolatedWorktree(repo, f"safety-{index}")
            # Line the workers up so their enter/exit calls actually race.
            barrier.wait()
            with wt_obj as wt:
                (wt / f"unit_{index}.txt").write_text(f"content {index}\n")
            branches[index] = wt_obj.branch

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly the four alc/* branches were created.
        created = [b for b in _branches(repo) if b.startswith("alc/")]
        assert len(created) == 4
        assert sorted(created) == sorted(branches.values())

        # Each branch's tree holds exactly its own unique file (plus the seed).
        for index, branch in branches.items():
            files = subprocess.run(
                ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", branch],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.split()
            assert f"unit_{index}.txt" in files
            for other in branches:
                if other != index:
                    assert f"unit_{other}.txt" not in files

        # The main working tree is untouched — only the seed file remains.
        working_files = [p.name for p in repo.iterdir() if p.name != ".git"]
        assert working_files == ["seed.txt"]


# ---------------------------------------------------------------------------
# (b) run_fanout over multiple blueprint units.
# ---------------------------------------------------------------------------


class TestRunFanout:
    def test_three_blueprint_units_all_succeed_in_order(self, tmp_path: Path) -> None:
        repo = _make_alc_repo(tmp_path)
        operator_layer = repo / ".alc"
        manifest = load_manifest(operator_layer)

        units = [
            {"kind": "blueprint", "name": "chore", "task": f"task-{i}"}
            for i in range(3)
        ]

        report = run_fanout(manifest, operator_layer, units, max_workers=3)

        assert report.success is True
        assert len(report.units) == 3
        # Order is preserved: unit i carries task-i.
        for i, unit in enumerate(report.units):
            assert unit.task == f"task-{i}"
            assert unit.kind == "blueprint"
            assert unit.success is True
            assert unit.run_report is not None
            assert unit.error is None


# ---------------------------------------------------------------------------
# (b2) run_fanout forwards the engine override to every unit.
# ---------------------------------------------------------------------------


_MANIFEST_TWO_ENGINES = """\
version: 1
default_engine: base
compute_tiers:
  standard:
    base: base-small
    chosen: chosen-small
engines:
  base:
    type: mock
  chosen:
    type: mock
blueprints_dir: .alc/blueprints
flows_dir: .alc/flows
queue_dir: .alc/queue
"""


class TestRunFanoutForwardsEngineOverride:
    def test_units_run_on_override_not_default(self, tmp_path: Path, monkeypatch) -> None:
        """A manifest default of 'base' plus override 'chosen' must dispatch on 'chosen'."""
        from alc.engine import Capabilities, EngineResult

        class _NamedMockEngine:
            def __init__(self, name: str) -> None:
                self.name = name

            def capabilities(self) -> Capabilities:
                return Capabilities()

            def health_check(self) -> bool:
                return True

            def run(self, request):
                return EngineResult(ok=True, output_text="[mock] applied")

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        alc = repo / ".alc"
        (alc / "blueprints").mkdir(parents=True)
        (alc / "flows").mkdir(parents=True)
        (alc / "manifest.yaml").write_text(_MANIFEST_TWO_ENGINES)
        (alc / "blueprints" / "chore.md").write_text(_CHORE)
        _commit_all(repo, "seed operator layer")

        operator_layer = alc
        manifest = load_manifest(operator_layer)

        # runner.py imports resolve_engine at module load, so patch there too:
        # that is the reference execute_mandate uses to build the RunReport's engine.
        monkeypatch.setattr(
            "alc.runner.resolve_engine",
            lambda name, engines: _NamedMockEngine(name),
        )

        units = [{"kind": "blueprint", "name": "chore", "task": "do it"}]
        report = run_fanout(
            manifest, operator_layer, units, max_workers=1, engine_override="chosen"
        )

        assert report.success is True
        assert report.units[0].run_report.engine == "chosen"


# ---------------------------------------------------------------------------
# (c) run_unit refuses a non-git directory.
# ---------------------------------------------------------------------------


class TestRunUnitRequiresGit:
    def test_non_git_dir_raises(self, operator_layer: Path) -> None:
        # operator_layer fixture lives in a plain tmp dir — not a git repo.
        with pytest.raises(RuntimeError):
            run_unit(
                manifest=load_manifest(operator_layer),
                operator_layer=operator_layer,
                kind="blueprint",
                name="chore",
                task="anything",
            )


# ---------------------------------------------------------------------------
# (d) Parallel queue drain path.
# ---------------------------------------------------------------------------


_TASK_YAML = """\
flow: ship
task: "tidy {index}"
engine: mock
isolate: false
"""


class TestProcessQueueParallel:
    def test_max_workers_drains_all_tasks_in_order(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)

        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        for i in range(3):
            (queue_dir / f"t{i}.yaml").write_text(_TASK_YAML.format(index=i))

        results = process_queue(manifest, operator_layer, max_workers=3)

        assert len(results) == 3
        assert all(r.success for r in results)
        # Order preserved: results follow the sorted pending order (t0, t1, t2).
        assert [r.task_file for r in results] == ["t0.yaml", "t1.yaml", "t2.yaml"]

        done_dir = queue_dir / "done"
        for i in range(3):
            assert (done_dir / f"t{i}.yaml").exists()
            assert (done_dir / f"t{i}.report.json").exists()
            assert not (queue_dir / f"t{i}.yaml").exists()
