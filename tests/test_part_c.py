# test_part_c.py — Part C: commit-in-worktree reconciliation.
#
# A committing demand flow (`commit.enabled`) run inside a git worktree
# (isolate:true) must commit ONCE — the worktree exit-commit, using the demand's
# rendered message, excluding `.alc/` — instead of firing both the FlowRunner's
# terminal commit and the worktree exit-commit (the old double-commit the queue
# guard refused). On failure the worktree is discarded (branch deleted, work
# vanishes). Fully hermetic: local git repo in tmp_path + Mock engine.
from __future__ import annotations

import subprocess
from pathlib import Path

from alc.flow import FlowRunner
from alc.intake import load_manifest
from alc.models import CommitSpec, FlowDefinition, FlowStage
from alc.queue import process_queue
from alc.worktree import IsolatedWorktree

# ---------------------------------------------------------------------------
# Harness — local git + Mock engine (mirrors tests/test_retry.py).
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

_CHORE_FAILING = """\
---
name: chore
purpose: Apply a low-risk, well-scoped maintenance change.
compute_tier: standard
checks:
  - name: always-fail
    command: ["false"]
---
# Workflow
1. Make the smallest change that satisfies the task.
"""

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

# A non-committing isolate flow (no commit: block) for the byte-identity check.
_SHIP_FLOW = """\
name: ship
description: A non-committing flow.
stages:
  - name: do
    blueprint: chore
"""

_DEMAND_TASK_ISOLATE = """\
flow: demand
task: "ship the widget"
engine: mock
isolate: true
"""

_SHIP_TASK_ISOLATE = """\
flow: ship
task: "tidy up"
engine: mock
isolate: true
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


def _build_repo(tmp_path: Path, chore: str) -> Path:
    """Build a git repo with an operator layer (demand + ship flows), seeded and
    committed; return the repo path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    alc = repo / ".alc"
    (alc / "blueprints").mkdir(parents=True)
    (alc / "flows").mkdir(parents=True)
    (alc / "queue").mkdir(parents=True)
    # A tracked `.alc/` file so a stage that mutates it can prove the exclude.
    (alc / "state.txt").write_text("seed state\n")
    (alc / "manifest.yaml").write_text(_MANIFEST)
    (alc / "blueprints" / "chore.md").write_text(chore)
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


def _branch_exists(repo: Path, branch: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo), "branch", "--list", branch],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip() != ""


def _branch_tree_files(repo: Path, branch: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", branch],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.splitlines()


# ---------------------------------------------------------------------------
# C1 — committing demand in a worktree that SUCCEEDS: exactly ONE commit,
#      the demand's message, `.alc/` excluded.
# ---------------------------------------------------------------------------


class TestCommittingDemandSuccess:
    def test_single_commit_excludes_alc(self, tmp_path: Path, monkeypatch) -> None:
        repo = _build_repo(tmp_path, chore=_CHORE_PASSING)
        # The stage writes a real feature file AND mutates a tracked `.alc/` file;
        # only the feature file must land on the branch (the `.alc/` change is the
        # queue/loop state that must never leak into a demand commit).
        engine = _write_files_engine(
            {"feature.txt": "the feature\n", ".alc/state.txt": "mutated by agent\n"}
        )
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine())

        manifest = load_manifest(repo / ".alc")

        queue_dir = repo / ".alc" / "queue"
        (queue_dir / "job1.yaml").write_text(_DEMAND_TASK_ISOLATE)

        results = process_queue(manifest, repo / ".alc")

        assert len(results) == 1
        r = results[0]
        assert r.success is True
        # The branch was recorded (the worktree committed) and is auto-mergeable.
        assert r.branch is not None
        branch = r.branch
        # Part E: the passed committing-demand branch was auto-merged into the
        # current branch and deleted — its work now lives on the current branch.
        assert r.auto_merge is True
        assert not _branch_exists(repo, branch)

        # The exit-commit is ONE non-merge commit — asserted on the demand's commit
        # that the merge brought in (found by its rendered flow.commit.message
        # subject; --no-merges excludes the auto-merge commit, which reuses it).
        rev = subprocess.run(
            ["git", "-C", str(repo), "rev-list", "--all", "--no-merges", "--grep",
             "^feat(auto): ship the widget$"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        assert len(rev) == 1
        demand_commit = rev[0]

        # The feature file IS in the exit-commit; the `.alc/` change is NOT.
        tree = _branch_tree_files(repo, demand_commit)
        assert "feature.txt" in tree
        # `.alc/state.txt` exists in the tree (it was tracked), but its mutation
        # must NOT be part of this commit — assert the committed blob is the seed.
        show = subprocess.run(
            ["git", "-C", str(repo), "show", f"{demand_commit}:.alc/state.txt"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert show.stdout == "seed state\n"

        # The merged feature landed on the current branch; the `.alc/` mutation
        # never did (it is excluded from the demand commit).
        head_tree = _branch_tree_files(repo, "HEAD")
        assert "feature.txt" in head_tree
        head_state = subprocess.run(
            ["git", "-C", str(repo), "show", "HEAD:.alc/state.txt"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert head_state.stdout == "seed state\n"


# ---------------------------------------------------------------------------
# C2 — committing demand in a worktree that FAILS: discarded (branch deleted,
#      no commit, changes gone).
# ---------------------------------------------------------------------------


class TestCommittingDemandFailure:
    def test_failure_discards_worktree(self, tmp_path: Path, monkeypatch) -> None:
        repo = _build_repo(tmp_path, chore=_CHORE_FAILING)
        engine = _write_files_engine({"feature.txt": "the feature\n"})
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine())

        manifest = load_manifest(repo / ".alc")
        queue_dir = repo / ".alc" / "queue"
        (queue_dir / "job1.yaml").write_text(_DEMAND_TASK_ISOLATE)

        results = process_queue(manifest, repo / ".alc")

        assert len(results) == 1
        r = results[0]
        assert r.report.success is False
        # No branch recorded, and no `alc/tick-*` branch left behind.
        assert r.branch is None
        branches = subprocess.run(
            ["git", "-C", str(repo), "branch", "--list", "alc/tick-*"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert branches.stdout.strip() == ""

        # The demand's file change is gone (never landed on any ref / worktree).
        assert not (repo / "feature.txt").exists()


# ---------------------------------------------------------------------------
# C3 — the OLD double-commit guard is gone: a committing flow + isolate:true
#      no longer returns the "not yet supported" refusal — it runs.
# ---------------------------------------------------------------------------


class TestOldGuardRemoved:
    def test_committing_isolate_flow_runs_not_refused(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        repo = _build_repo(tmp_path, chore=_CHORE_PASSING)
        engine = _write_files_engine({"feature.txt": "the feature\n"})
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine())

        manifest = load_manifest(repo / ".alc")
        queue_dir = repo / ".alc" / "queue"
        (queue_dir / "job1.yaml").write_text(_DEMAND_TASK_ISOLATE)

        results = process_queue(manifest, repo / ".alc")

        assert len(results) == 1
        r = results[0]
        # It RAN (succeeded + committed to a branch), rather than being refused.
        assert r.success is True
        assert r.branch is not None
        # The refusal message never appears in the report.
        report_text = r.report.model_dump_json()
        assert "not yet supported with worktree isolation" not in report_text


# ---------------------------------------------------------------------------
# C4 — byte-identity: a NON-committing isolate flow still commits INCLUDING
#      `.alc/` (exclude_paths=() default), and FlowRunner.run(skip_commit=...)
#      gates the terminal commit + revert.
# ---------------------------------------------------------------------------


class TestByteIdentity:
    def test_non_committing_isolate_flow_commits_including_alc(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """A non-committing isolate flow uses exclude_paths=() -> the exit-commit
        still includes a `.alc/` file, exactly as before Part C."""
        repo = _build_repo(tmp_path, chore=_CHORE_PASSING)
        engine = _write_files_engine(
            {"feature.txt": "the feature\n", ".alc/note.txt": "loop state\n"}
        )
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine())

        manifest = load_manifest(repo / ".alc")
        queue_dir = repo / ".alc" / "queue"
        (queue_dir / "job1.yaml").write_text(_SHIP_TASK_ISOLATE)

        results = process_queue(manifest, repo / ".alc")

        assert len(results) == 1
        r = results[0]
        assert r.success is True
        assert r.branch is not None
        tree = _branch_tree_files(repo, r.branch)
        # The default exclude_paths=() commits everything, incl. the new `.alc/` file.
        assert "feature.txt" in tree
        assert ".alc/note.txt" in tree

    def _write_dev_flow(self, operator_layer: Path, commit_message: str) -> FlowDefinition:
        return FlowDefinition(
            name="demand",
            stages=[FlowStage(name="do", blueprint="chore")],
            commit=CommitSpec(enabled=True, message=commit_message),
        )

    def test_skip_commit_true_no_commit_no_revert_on_failure(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """FlowRunner.run(skip_commit=True) on a FAILING committing flow leaves
        commit_sha None AND does not revert the failed flow's files."""
        repo = _build_repo(tmp_path, chore=_CHORE_FAILING)
        # The failing chore stage writes a file; skip_commit=True must NOT revert it.
        engine = _write_files_engine({"feature.txt": "the feature\n"})
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine())
        monkeypatch.chdir(repo)

        manifest = load_manifest(repo / ".alc")
        flow = self._write_dev_flow(repo / ".alc", "feat(auto): {task}")
        runner = FlowRunner(manifest=manifest, operator_layer=repo / ".alc")

        report = runner.run(
            flow=flow, task="ship it", engine_override="mock", skip_commit=True
        )

        assert report.success is False
        assert report.commit_sha is None
        # skip_commit skipped the revert-on-failure: the file the stage wrote stays.
        assert (repo / "feature.txt").exists()

    def test_skip_commit_false_still_reverts_on_failure(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The default (skip_commit=False) still reverts a failed committing flow —
        proving the gate only changes behavior when explicitly set."""
        repo = _build_repo(tmp_path, chore=_CHORE_FAILING)
        engine = _write_files_engine({"feature.txt": "the feature\n"})
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine())
        monkeypatch.chdir(repo)

        manifest = load_manifest(repo / ".alc")
        flow = self._write_dev_flow(repo / ".alc", "feat(auto): {task}")
        runner = FlowRunner(manifest=manifest, operator_layer=repo / ".alc")

        report = runner.run(flow=flow, task="ship it", engine_override="mock")

        assert report.success is False
        assert report.commit_sha is None
        # Default behavior reverts the failed demand's untracked file.
        assert not (repo / "feature.txt").exists()

    def test_skip_commit_false_still_commits_on_success(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The default (skip_commit=False) still runs the terminal commit on a
        green committing flow — commit_sha is set."""
        repo = _build_repo(tmp_path, chore=_CHORE_PASSING)
        engine = _write_files_engine({"feature.txt": "the feature\n"})
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine())
        monkeypatch.chdir(repo)

        manifest = load_manifest(repo / ".alc")
        flow = self._write_dev_flow(repo / ".alc", "feat(auto): {task}")
        runner = FlowRunner(manifest=manifest, operator_layer=repo / ".alc")

        report = runner.run(flow=flow, task="ship it", engine_override="mock")

        assert report.success is True
        assert report.commit_sha is not None


# ---------------------------------------------------------------------------
# C5 — unit: IsolatedWorktree exclude_paths / commit_on_exit routing.
# ---------------------------------------------------------------------------


def _make_git_repo(base: Path) -> Path:
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
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True, capture_output=True)
    return repo


class TestIsolatedWorktreeExcludeAndDiscard:
    def test_exclude_paths_keeps_alc_out_of_exit_commit(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        wt = IsolatedWorktree(
            repo, "test", commit_message="wip: {branch}", exclude_paths=(".alc/",)
        )
        with wt as path:
            (path / "feature.txt").write_text("kept\n")
            (path / ".alc").mkdir()
            (path / ".alc" / "state.txt").write_text("excluded\n")

        assert wt.committed is True
        tree = _branch_tree_files(repo, wt.branch)
        assert "feature.txt" in tree
        assert ".alc/state.txt" not in tree
        subprocess.run(["git", "-C", str(repo), "branch", "-D", wt.branch], capture_output=True)

    def test_commit_on_exit_false_discards_branch(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        wt = IsolatedWorktree(repo, "test")
        with wt as path:
            # The agent wrote a file, but the owner discards the work on exit.
            (path / "feature.txt").write_text("thrown away\n")
            wt.commit_on_exit = False

        assert wt.committed is False
        # Branch was deleted (nothing committed even though a file was written).
        assert not _branch_exists(repo, wt.branch)
        assert not (repo / "feature.txt").exists()
