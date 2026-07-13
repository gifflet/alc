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

# A single-stage flow that only references the chore blueprint.
_SINGLE_FLOW = """\
name: single
description: One-stage flow for isolated queue drain tests.
stages:
  - name: do
    blueprint: chore
"""

# A specialist that acts through the chore blueprint.
_SPECIALIST_DEV = """\
name: dev
area: the test codebase
blueprint: chore
knowledge_path: .alc/specialists/dev.knowledge.md
"""

# A manifest that provisions a gitignored runtime file into each worktree.
_MANIFEST_PROVISION = """\
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
worktree_provision:
  - copy: data/seed.txt
"""

# A blueprint whose check asserts the provisioned file is present in the worktree.
_PROBE = """\
---
name: probe
purpose: Assert the worktree was provisioned.
compute_tier: standard
checks:
  - name: data-present
    command: ["test", "-f", "data/seed.txt"]
---
# Workflow
1. Do nothing; the check asserts the provisioned runtime file is present.
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
    (alc / "flows" / "single.yaml").write_text(_SINGLE_FLOW)

    _commit_all(repo, "seed operator layer")
    return repo


def _make_gitignored_alc_repo(base: Path) -> Path:
    """Build a git repo whose .alc/ Operator Layer is GITIGNORED (untracked).

    ``git worktree add`` checks out only tracked files, so a fresh worktree does
    NOT contain .alc/ — mirroring a real dogfood project. A conduct specialist
    unit must still resolve its definition from the main .alc/.
    """
    repo = base / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / ".gitignore").write_text(".alc/\n")
    (repo / "seed.txt").write_text("x\n")
    _commit_all(repo, "seed (no .alc committed)")

    alc = repo / ".alc"
    (alc / "blueprints").mkdir(parents=True)
    (alc / "specialists").mkdir(parents=True)
    (alc / "manifest.yaml").write_text(_MANIFEST)
    (alc / "blueprints" / "chore.md").write_text(_CHORE)
    (alc / "specialists" / "dev.yaml").write_text(_SPECIALIST_DEV)
    # Deliberately NOT committed: .alc/ is gitignored, so a worktree omits it.
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


class TestRunUnitGitignoredOperatorLayer:
    """A specialist unit must run even when .alc/ is gitignored: the fresh
    worktree omits the (untracked) Operator Layer, so the Specialist must fall
    back to the main .alc/ instead of raising FileNotFoundError."""

    def test_specialist_unit_falls_back_to_main_operator_layer(
        self, tmp_path: Path
    ) -> None:
        repo = _make_gitignored_alc_repo(tmp_path)
        operator_layer = repo / ".alc"
        manifest = load_manifest(operator_layer)

        units = [{"kind": "specialist", "name": "dev", "task": "tidy the module"}]
        report = run_fanout(manifest, operator_layer, units, max_workers=1)

        assert report.success is True
        unit = report.units[0]
        assert unit.kind == "specialist"
        assert unit.success is True
        assert unit.error is None
        assert unit.specialist_report is not None


# ---------------------------------------------------------------------------
# (d) Parallel queue drain path.
# ---------------------------------------------------------------------------


_TASK_YAML = """\
flow: ship
task: "tidy {index}"
engine: mock
isolate: false
"""

_TASK_YAML_ISOLATE = """\
flow: single
task: "isolated-task-{index}"
engine: mock
isolate: true
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


# ---------------------------------------------------------------------------
# (e) Parallel queue drain with isolate:true tasks in a real git repo.
# ---------------------------------------------------------------------------


class TestProcessQueueParallelIsolated:
    """process_queue's ThreadPoolExecutor branch with isolate:true tasks."""

    def test_two_isolated_tasks_run_concurrently_and_are_archived(
        self, tmp_path: Path
    ) -> None:
        """2 isolate:true tasks in a git repo, max_workers=2 -> both archived in order.

        The mock engine writes nothing, so IsolatedWorktree finds no staged changes
        and cleans up the temporary branches.  We therefore assert:
        - 2 successful TickResults in original (sorted) order.
        - Both task files and their reports are archived to done/.
        - No stray worktrees remain (git worktree list shows only the main tree).
        """
        repo = _make_alc_repo(tmp_path)
        operator_layer = repo / ".alc"
        manifest = load_manifest(operator_layer)

        queue_dir = repo / manifest.queue_dir
        queue_dir.mkdir(parents=True, exist_ok=True)
        for i in range(2):
            (queue_dir / f"p{i}.yaml").write_text(_TASK_YAML_ISOLATE.format(index=i))

        results = process_queue(manifest, operator_layer, max_workers=2)

        # Both tasks were processed successfully and are in the original sorted order.
        assert len(results) == 2
        assert all(r.success for r in results), [r for r in results if not r.success]
        assert [r.task_file for r in results] == ["p0.yaml", "p1.yaml"]

        # Each task file and its Gate report are in done/.
        done_dir = queue_dir / "done"
        for i in range(2):
            assert (done_dir / f"p{i}.yaml").exists(), f"p{i}.yaml not archived"
            assert (done_dir / f"p{i}.report.json").exists(), f"p{i}.report.json missing"
            assert not (queue_dir / f"p{i}.yaml").exists(), f"p{i}.yaml still in queue"

        # No stray worktrees: only the main working tree should remain.
        wt_list = subprocess.run(
            ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        # Each worktree entry starts with "worktree <path>"; there must be exactly one.
        worktree_entries = [
            line for line in wt_list.splitlines() if line.startswith("worktree ")
        ]
        assert len(worktree_entries) == 1, f"Stray worktrees found:\n{wt_list}"


class TestProcessQueueIsolatedSpecialistGitignored:
    """The isolated queue drain (cycles/loops) must run a specialist task even
    when .alc/ is gitignored — the fresh worktree omits the untracked Operator
    Layer, so the Specialist falls back to the main .alc/ (same as fan-out)."""

    def test_isolated_specialist_task_falls_back_to_main_operator_layer(
        self, tmp_path: Path
    ) -> None:
        repo = _make_gitignored_alc_repo(tmp_path)
        operator_layer = repo / ".alc"
        manifest = load_manifest(operator_layer)

        queue_dir = repo / manifest.queue_dir
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "s0.yaml").write_text(
            "kind: specialist\nname: dev\ntask: tidy the module\nisolate: true\n"
        )

        results = process_queue(manifest, operator_layer, max_workers=1)

        assert len(results) == 1
        assert results[0].success is True, results[0]
        assert (queue_dir / "done" / "s0.yaml").exists()


class TestRunFanoutProvisionsWorktree:
    """A fan-out unit must provision gitignored runtime deps into its worktree —
    parity with the queue drain. Without it a `needs_service` qa (or any check
    that reads a provisioned path, e.g. the SQLite data dir) fails because the
    file was never checked out into the fresh worktree."""

    def test_provisioned_file_is_present_in_the_worktree(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        (repo / ".gitignore").write_text("data/\n")
        alc = repo / ".alc"
        (alc / "blueprints").mkdir(parents=True)
        (alc / "flows").mkdir(parents=True)
        (alc / "manifest.yaml").write_text(_MANIFEST_PROVISION)
        (alc / "blueprints" / "probe.md").write_text(_PROBE)
        _commit_all(repo, "seed operator layer (data/ gitignored)")
        # Gitignored runtime data lives only in the main tree (never committed),
        # so a fresh worktree lacks it unless provisioning copies it in.
        (repo / "data").mkdir()
        (repo / "data" / "seed.txt").write_text("db\n")

        operator_layer = alc
        manifest = load_manifest(operator_layer)
        units = [{"kind": "blueprint", "name": "probe", "task": "probe"}]
        report = run_fanout(manifest, operator_layer, units, max_workers=1)

        assert report.success is True, report.units[0].error
        assert report.units[0].success is True


class TestRunConductParallelMerges:
    """A `run` conduct must APPLY its work: after a successful --parallel dispatch
    the unit branches are integrated into HEAD (like the queue drain), not left
    stranded. Conflicting branches surface as `left`."""

    def test_successful_unit_branch_is_merged_into_head(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from alc.conduct import conduct
        from alc.models import ConductorPlan, FanoutReport, PlannedUnit, UnitResult

        repo = _make_alc_repo(tmp_path)
        operator_layer = repo / ".alc"
        manifest = load_manifest(operator_layer)

        base = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        # A real branch holding one commit that HEAD does not have — the artifact a
        # successful fan-out unit would leave behind.
        subprocess.run(
            ["git", "-C", str(repo), "checkout", "-q", "-b", "alc/fanout-dev-x"],
            check=True, capture_output=True,
        )
        (repo / "fix.txt").write_text("fixed\n")
        _commit_all(repo, "feat(auto): fix")
        subprocess.run(
            ["git", "-C", str(repo), "checkout", "-q", base],
            check=True, capture_output=True,
        )
        assert not (repo / "fix.txt").exists()  # HEAD lacks the fix pre-merge

        canned_plan = ConductorPlan(
            items=[PlannedUnit(kind="specialist", name="dev", task="x")]
        )
        monkeypatch.setattr("alc.conduct.plan_flows", lambda *a, **k: canned_plan)
        canned_fanout = FanoutReport(
            units=[
                UnitResult(
                    kind="specialist", name="dev", task="x",
                    success=True, branch="alc/fanout-dev-x",
                )
            ],
            success=True,
        )
        monkeypatch.setattr("alc.fanout.run_fanout", lambda *a, **k: canned_fanout)

        report = conduct(manifest, operator_layer, "goal", parallel=True)

        assert report.merged == ["alc/fanout-dev-x"]
        assert report.left == []
        assert (repo / "fix.txt").read_text() == "fixed\n"  # applied to HEAD
        assert "alc/fanout-dev-x" not in _branches(repo)  # merged branch deleted
