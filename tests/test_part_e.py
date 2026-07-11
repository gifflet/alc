# test_part_e.py — Part E: parallel drain wiring + post-batch auto-merge.
#
# After a drain batch, the branches produced by SUCCESSFUL committing demands
# (Part C's worktree exit-commits) are auto-merged into the current branch via
# Part D's auto_merge_branches — but branches from ordinary non-committing
# isolate tasks are LEFT for manual review (existing contract). Default
# concurrency 1 with no committing-demand-in-worktree stays byte-identical.
# Fully hermetic: local git repo in tmp_path + Mock engine.
from __future__ import annotations

import subprocess
from pathlib import Path

from alc.intake import load_manifest
from alc.queue import _topological_waves, process_queue

# ---------------------------------------------------------------------------
# Harness — local git + Mock engine (mirrors tests/test_part_c.py).
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

_CHORE_PASSING = """\
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

# A committing demand flow: commits on success (Part C reconciles the single
# worktree exit-commit).
_DEMAND_FLOW = """\
name: demand
description: A unit of demand work that commits on success.
stages:
  - name: do
    blueprint: chore
commit:
  enabled: true
  message: "feat(auto): {task}"
"""

# A non-committing isolate flow (no commit: block) — its worktree branch is left
# for manual review, never auto-merged.
_SHIP_FLOW = """\
name: ship
description: A non-committing flow.
stages:
  - name: do
    blueprint: chore
"""

_SHIP_TASK_ISOLATE = """\
flow: ship
task: "tidy up"
engine: mock
isolate: true
"""

# A committing demand run in the SHARED workdir (isolate:false) — the standard
# serial cycle. Commits directly to the current branch, no worktree branch.
_DEMAND_TASK_SHARED = """\
flow: demand
task: "shared cycle"
engine: mock
isolate: false
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
    """Build a git repo with an operator layer (demand + ship flows), seeded and
    committed; return the repo path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    alc = repo / ".alc"
    (alc / "blueprints").mkdir(parents=True)
    (alc / "flows").mkdir(parents=True)
    (alc / "queue").mkdir(parents=True)
    (alc / "manifest.yaml").write_text(_MANIFEST)
    (alc / "blueprints" / "chore.md").write_text(_CHORE_PASSING)
    (alc / "flows" / "demand.yaml").write_text(_DEMAND_FLOW)
    (alc / "flows" / "ship.yaml").write_text(_SHIP_FLOW)
    _commit_all(repo, "seed operator layer")
    return repo


def _write_files_engine(files: dict[str, str]):
    """Return a MockEngine-like class writing each rel_path->content into the
    request workdir on every turn."""
    from alc.engine import Capabilities, EngineResult

    class _WriteFilesEngine:
        name = "mock"

        def capabilities(self) -> Capabilities:
            return Capabilities()

        def health_check(self) -> bool:
            return True

        def run(self, request):
            for rel_path, content in files.items():
                dst = request.workdir / rel_path
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(content)
            return EngineResult(ok=True, output_text="[mock] wrote files")

    return _WriteFilesEngine


def _per_task_files_engine(mapping: dict[str, dict[str, str]]):
    """Return a MockEngine-like class that writes a DISJOINT file set per demand,
    keyed by a substring of the rendered task (so three concurrent worktrees each
    get their own file). Falls back to writing nothing when no key matches."""
    from alc.engine import Capabilities, EngineResult

    class _PerTaskEngine:
        name = "mock"

        def capabilities(self) -> Capabilities:
            return Capabilities()

        def health_check(self) -> bool:
            return True

        def run(self, request):
            directive = request.directive
            for key, files in mapping.items():
                if key in directive:
                    for rel_path, content in files.items():
                        dst = request.workdir / rel_path
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        dst.write_text(content)
                    break
            return EngineResult(ok=True, output_text="[mock] wrote files")

    return _PerTaskEngine


def _branch_exists(repo: Path, branch: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo), "branch", "--list", branch],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip() != ""


def _list_tick_branches(repo: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), "branch", "--list", "alc/tick-*", "--format=%(refname:short)"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [b for b in result.stdout.splitlines() if b.strip()]


def _head_tree_files(repo: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.splitlines()


def _git_log_subjects(repo: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), "log", "--format=%s"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.splitlines()


# The three DISJOINT-file committing demands used by E1 + E2. Each task's title
# is a unique key the per-task engine matches to write its own feature file.
_THREE_DEMANDS = {
    "alpha": {"alpha.txt": "alpha feature\n"},
    "bravo": {"bravo.txt": "bravo feature\n"},
    "charlie": {"charlie.txt": "charlie feature\n"},
}


def _enqueue_three_demands(queue_dir: Path) -> None:
    for i, title in enumerate(_THREE_DEMANDS, start=1):
        (queue_dir / f"job{i}.yaml").write_text(
            f"flow: demand\ntask: \"{title}\"\nengine: mock\nisolate: true\n"
        )


# ---------------------------------------------------------------------------
# E1 — the PRD case: three committing demands run concurrently in worktrees,
#      then the passed branches auto-merge into main (branches gone, all three
#      files on HEAD, every result success + auto_merge True + branch set).
# ---------------------------------------------------------------------------


class TestParallelDemandsAutoMerge:
    def test_concurrency_three_merges_all_branches(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        repo = _build_repo(tmp_path)
        engine = _per_task_files_engine(_THREE_DEMANDS)
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine())

        manifest = load_manifest(repo / ".alc")
        queue_dir = repo / ".alc" / "queue"
        _enqueue_three_demands(queue_dir)

        results = process_queue(manifest, repo / ".alc", max_workers=3)

        assert len(results) == 3
        for r in results:
            assert r.success is True
            assert r.auto_merge is True
            assert r.branch is not None

        # Every demand branch was merged and then deleted — none left behind.
        assert _list_tick_branches(repo) == []

        # main HEAD now contains all three disjoint feature files.
        tree = _head_tree_files(repo)
        assert "alpha.txt" in tree
        assert "bravo.txt" in tree
        assert "charlie.txt" in tree


# ---------------------------------------------------------------------------
# E2 — concurrency=1 parity: the SAME three committing demands with a serial
#      drain end up in the identical state (all merged, branches deleted). Proves
#      the serial and parallel paths share the one auto-merge tail.
# ---------------------------------------------------------------------------


class TestSerialDrainAlsoMerges:
    def test_concurrency_one_merges_all_branches(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        repo = _build_repo(tmp_path)
        engine = _per_task_files_engine(_THREE_DEMANDS)
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine())

        manifest = load_manifest(repo / ".alc")
        queue_dir = repo / ".alc" / "queue"
        _enqueue_three_demands(queue_dir)

        results = process_queue(manifest, repo / ".alc", max_workers=1)

        assert len(results) == 3
        for r in results:
            assert r.success is True
            assert r.auto_merge is True
            assert r.branch is not None

        # Identical end state to E1: branches merged + deleted, files on HEAD.
        assert _list_tick_branches(repo) == []
        tree = _head_tree_files(repo)
        assert "alpha.txt" in tree
        assert "bravo.txt" in tree
        assert "charlie.txt" in tree


# ---------------------------------------------------------------------------
# E3 — byte-identity: a plain non-committing isolate task's branch is NOT merged.
#      Its branch STILL EXISTS after the drain and auto_merge is False (the
#      "leave the isolate branch for review" contract is intact).
# ---------------------------------------------------------------------------


class TestPlainIsolateNotMerged:
    def test_non_committing_isolate_branch_left_for_review(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        repo = _build_repo(tmp_path)
        engine = _write_files_engine({"feature.txt": "the feature\n"})
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine())

        manifest = load_manifest(repo / ".alc")
        queue_dir = repo / ".alc" / "queue"
        (queue_dir / "job1.yaml").write_text(_SHIP_TASK_ISOLATE)

        results = process_queue(manifest, repo / ".alc", max_workers=1)

        assert len(results) == 1
        r = results[0]
        assert r.success is True
        assert r.branch is not None
        # A plain isolate branch is NOT auto-mergeable and is left in place.
        assert r.auto_merge is False
        assert _branch_exists(repo, r.branch)
        # Its file lives only on the isolate branch, not on main HEAD.
        assert "feature.txt" not in _head_tree_files(repo)


# ---------------------------------------------------------------------------
# E4 — byte-identity: a committing demand with isolate:false (today's shared
#      workdir standard cycle) commits directly to the current branch, has no
#      worktree branch, auto_merge False, and no auto-merge pass runs.
# ---------------------------------------------------------------------------


class TestSharedWorkdirStandardCycle:
    def test_isolate_false_commits_to_current_branch(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        repo = _build_repo(tmp_path)
        engine = _write_files_engine({"shared.txt": "shared work\n"})
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine())
        # The shared-workdir standard cycle runs in the project root cwd (isolate
        # False -> workdir None -> Path.cwd()), like the real drain.
        monkeypatch.chdir(repo)

        manifest = load_manifest(repo / ".alc")
        queue_dir = repo / ".alc" / "queue"
        (queue_dir / "job1.yaml").write_text(_DEMAND_TASK_SHARED)

        results = process_queue(manifest, repo / ".alc", max_workers=1)

        assert len(results) == 1
        r = results[0]
        assert r.success is True
        # No worktree branch and not auto-mergeable — no auto-merge pass runs.
        assert r.branch is None
        assert r.auto_merge is False
        # The commit landed directly on the current branch (no alc/tick-* branch).
        assert _list_tick_branches(repo) == []
        assert "shared.txt" in _head_tree_files(repo)
        assert _git_log_subjects(repo)[0] == "feat(auto): shared cycle"


# ---------------------------------------------------------------------------
# W1 — _topological_waves: the pure scheduling ordering (no engine, no git).
# ---------------------------------------------------------------------------


def _write_task(queue_dir: Path, stem: str, *, id: str | None = None,
                depends_on: list[str] | None = None) -> Path:
    """Write a minimal committing-demand task file with optional id/depends_on."""
    lines = ["flow: demand", f'task: "{stem}"', "engine: mock", "isolate: true"]
    if id is not None:
        lines.append(f"id: {id}")
    if depends_on is not None:
        lines.append(f"depends_on: [{', '.join(depends_on)}]")
    path = queue_dir / f"{stem}.yaml"
    path.write_text("\n".join(lines) + "\n")
    return path


class TestTopologicalWaves:
    def test_no_deps_is_single_sorted_wave(self, tmp_path: Path) -> None:
        q = tmp_path
        _write_task(q, "b")
        _write_task(q, "a")
        _write_task(q, "c")
        pending = sorted(q.glob("*.yaml"))

        waves = _topological_waves(pending)

        assert waves == [sorted(pending)]

    def test_linear_chain_is_three_ordered_waves(self, tmp_path: Path) -> None:
        q = tmp_path
        a = _write_task(q, "a", id="A")
        b = _write_task(q, "b", id="B", depends_on=["A"])
        c = _write_task(q, "c", id="C", depends_on=["B"])
        pending = sorted(q.glob("*.yaml"))

        waves = _topological_waves(pending)

        assert waves == [[a], [b], [c]]

    def test_diamond_orders_join_after_both_arms(self, tmp_path: Path) -> None:
        q = tmp_path
        a = _write_task(q, "a", id="A")
        b = _write_task(q, "b", id="B", depends_on=["A"])
        c = _write_task(q, "c", id="C", depends_on=["A"])
        d = _write_task(q, "d", id="D", depends_on=["B", "C"])
        pending = sorted(q.glob("*.yaml"))

        waves = _topological_waves(pending)

        assert waves == [[a], [b, c], [d]]

    def test_cycle_does_not_hang_and_collapses(self, tmp_path: Path, capsys) -> None:
        q = tmp_path
        # A depends_on B and B depends_on A -> a cycle; neither is ever ready.
        a = _write_task(q, "a", id="A", depends_on=["B"])
        b = _write_task(q, "b", id="B", depends_on=["A"])
        pending = sorted(q.glob("*.yaml"))

        waves = _topological_waves(pending)

        # Everything collapses into one final wave (sorted); a warning is printed.
        assert waves == [[a, b]]
        assert "dependency cycle" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# W2 — the key integration test: a dependent demand's worktree branches off a
#      main that ALREADY contains its precedent's merged file (waved drain).
# ---------------------------------------------------------------------------


class TestWavedDrainDependentBranchesOffMergedPrecedent:
    def test_dependent_sees_merged_precedent_file(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        repo = _build_repo(tmp_path)
        # `wire` (depends_on ingest) reads ingest.txt and, only if it exists,
        # writes wire.txt — so its file lands ONLY when its worktree branched off
        # a main that already carries ingest's merged commit.
        from alc.engine import Capabilities, EngineResult

        class _DepAwareEngine:
            name = "mock"

            def capabilities(self) -> Capabilities:
                return Capabilities()

            def health_check(self) -> bool:
                return True

            def run(self, request):
                if "ingest" in request.directive:
                    (request.workdir / "ingest.txt").write_text("ingest\n")
                elif "wire" in request.directive:
                    # Only proceed when the precedent's merged file is present.
                    if (request.workdir / "ingest.txt").exists():
                        (request.workdir / "wire.txt").write_text("wire\n")
                return EngineResult(ok=True, output_text="[mock] wrote files")

        monkeypatch.setattr(
            "alc.runner.resolve_engine", lambda name, cfg: _DepAwareEngine()
        )

        manifest = load_manifest(repo / ".alc")
        queue_dir = repo / ".alc" / "queue"
        # 00 sorts before 01, but wire declares depends_on ingest, so the wave
        # scheduler runs ingest FIRST and merges it before wire's wave.
        _write_task(queue_dir, "job-00-ingest", id="ingest")
        _write_task(queue_dir, "job-01-wire", id="wire", depends_on=["ingest"])

        results = process_queue(manifest, repo / ".alc", max_workers=3)

        assert len(results) == 2
        for r in results:
            assert r.success is True
            assert r.auto_merge is True
            assert r.merged is True

        # Both branches merged and deleted; main HEAD carries BOTH files. wire.txt
        # only exists because wire's worktree saw ingest's already-merged file.
        assert _list_tick_branches(repo) == []
        tree = _head_tree_files(repo)
        assert "ingest.txt" in tree
        assert "wire.txt" in tree


# ---------------------------------------------------------------------------
# W3 — byte-identity: with NO depends_on the waved drain is one wave of all
#      pending with one trailing auto-merge; identical end state at both
#      concurrencies, results in sorted-pending order.
# ---------------------------------------------------------------------------


class TestNoDepsWaveIsByteIdentical:
    def test_single_wave_same_end_state_and_order(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        for max_workers in (1, 3):
            base = tmp_path / f"w{max_workers}"
            base.mkdir()
            repo = _build_repo(base)
            engine = _per_task_files_engine(_THREE_DEMANDS)
            monkeypatch.setattr(
                "alc.runner.resolve_engine", lambda name, cfg: engine()
            )

            manifest = load_manifest(repo / ".alc")
            queue_dir = repo / ".alc" / "queue"
            _enqueue_three_demands(queue_dir)
            pending = sorted(queue_dir.glob("*.yaml"))

            results = process_queue(manifest, repo / ".alc", max_workers=max_workers)

            # Results are returned in sorted-pending order.
            assert [r.task_file for r in results] == [p.name for p in pending]
            # All three demands merged this single wave.
            for r in results:
                assert r.success is True
                assert r.auto_merge is True
                assert r.merged is True
            assert _list_tick_branches(repo) == []
            tree = _head_tree_files(repo)
            assert "alpha.txt" in tree
            assert "bravo.txt" in tree
            assert "charlie.txt" in tree


# ---------------------------------------------------------------------------
# W4 — the honest run_cycle metric: a cycle with 1 MERGED + 1 LEFT (conflict)
#      lands merged==1, left==1 on the CycleRecord and in the summary.
# ---------------------------------------------------------------------------


class TestRunCycleMergedLeftMetric:
    def test_one_merged_one_left(self, tmp_path: Path, monkeypatch) -> None:
        from alc.engine import Capabilities, EngineResult
        from alc.intake import load_loop
        from alc.loop import format_cycle_summary, loops_dir, run_cycle
        from alc.models import LoopState

        repo = _build_repo(tmp_path)

        # Two independent committing demands that BOTH write the SAME file with
        # DIFFERENT content. Within one wave the first-sorted branch merges clean;
        # the second conflicts on that file and is LEFT.
        class _SameFileEngine:
            name = "mock"

            def capabilities(self) -> Capabilities:
                return Capabilities()

            def health_check(self) -> bool:
                return True

            def run(self, request):
                content = "one\n" if "one" in request.directive else "two\n"
                (request.workdir / "clash.txt").write_text(content)
                return EngineResult(ok=True, output_text="[mock] wrote clash")

        monkeypatch.setattr(
            "alc.runner.resolve_engine", lambda name, cfg: _SameFileEngine()
        )

        # Mode B drain-only loop with concurrency 2 (both demands in one wave).
        loops = repo / ".alc" / "loops"
        loops.mkdir(parents=True)
        (loops / "deliver.yaml").write_text(
            "name: deliver\nstop:\n  max_cycles: 20\ndrain:\n  concurrency: 2\n"
        )
        queue_dir = repo / ".alc" / "queue"
        _write_task(queue_dir, "job-00-one")
        _write_task(queue_dir, "job-01-two")

        manifest = load_manifest(repo / ".alc")
        loop_def = load_loop(loops_dir(manifest, repo / ".alc"), "deliver")
        _new_state, record = run_cycle(
            manifest, repo / ".alc", loop_def, LoopState(name="deliver"),
            engine_override="mock",
        )

        assert record.merged == 1
        assert record.left == 1
        assert "merged=1 left=1" in format_cycle_summary(record)
        # The clean branch was deleted; the conflicting one is left for review.
        assert len(_list_tick_branches(repo)) == 1
