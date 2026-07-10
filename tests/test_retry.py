# test_retry.py — Hermetic tests for the queue auto-retry-with-feedback feature.
#
# Coverage:
#   (1) build_retry_task: increments retries, appends the delimited feedback
#       section, preserves every other field, truncates the failure output.
#   (2) write_retry_task: writes a PENDING *.yaml into queue_dir (not done/),
#       re-loadable as a QueueTask, filename signals a retry.
#   (3) Drain auto-retry end-to-end on a real LOCAL git repo + file-writing Mock
#       engine: a failing committing demand flow is re-enqueued with the failure
#       output embedded; the retry drains and succeeds next pass; a task already
#       at the cap is NOT re-enqueued (bounded).
#   (4) Backward compat: max_task_retries unset (0) writes NO retry file.
from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from alc.intake import load_manifest
from alc.models import QueueTask
from alc.queue import build_retry_task, process_queue, write_retry_task

# ---------------------------------------------------------------------------
# Harness — mirrors tests/test_cycle_standard.py (local git + Mock engine).
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
max_task_retries: {max_retries}
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

# A committing demand flow, run non-isolated (isolate:false) so the queue's
# double-commit guard permits it and the drain runs it in the shared workdir.
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

_DEMAND_TASK = """\
flow: demand
task: "ship the widget"
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


def _build_repo(tmp_path: Path, chore: str, max_retries: int) -> Path:
    """Build a git repo with an operator layer (demand flow); return the repo path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    alc = repo / ".alc"
    (alc / "blueprints").mkdir(parents=True)
    (alc / "flows").mkdir(parents=True)
    (alc / "queue").mkdir(parents=True)
    (alc / "manifest.yaml").write_text(_MANIFEST.format(max_retries=max_retries))
    (alc / "blueprints" / "chore.md").write_text(chore)
    (alc / "flows" / "demand.yaml").write_text(_DEMAND_FLOW)
    _commit_all(repo, "seed operator layer")
    return repo


def _write_file_engine(rel_path: str, content: str = "written by engine\n"):
    """Return a MockEngine-like class that writes a file into the request workdir."""
    from alc.engine import Capabilities, EngineResult

    class _WriteFileEngine:
        name = "mock"

        def capabilities(self) -> Capabilities:
            return Capabilities()

        def health_check(self) -> bool:
            return True

        def run(self, request):
            (request.workdir / rel_path).write_text(content)
            return EngineResult(ok=True, output_text="[mock] wrote a file")

    return _WriteFileEngine


def _pending_yaml(queue_dir: Path) -> list[Path]:
    """Return pending *.yaml files (top-level, not under done/)."""
    return sorted(queue_dir.glob("*.yaml"))


# ---------------------------------------------------------------------------
# (1) build_retry_task
# ---------------------------------------------------------------------------


class TestBuildRetryTask:
    def test_increments_retries_and_appends_feedback(self) -> None:
        qt = QueueTask(flow="demand", task="do the thing", engine="mock", isolate=False)
        retry = build_retry_task(qt, "check always-fail failed: exit 1")

        assert retry.retries == qt.retries + 1  # 0 -> 1
        # Original text and the failure output are both present.
        assert "do the thing" in retry.task
        assert "check always-fail failed: exit 1" in retry.task
        # A clearly delimited feedback section is present.
        assert "Previous attempt failed" in retry.task

    def test_preserves_every_other_field(self) -> None:
        qt = QueueTask(
            kind="specialist",
            name="db",
            task="document the area",
            engine="mock",
            isolate=True,
            retries=2,
        )
        retry = build_retry_task(qt, "boom")

        assert retry.kind == "specialist"
        assert retry.name == "db"
        assert retry.engine == "mock"
        assert retry.isolate is True
        assert retry.flow == qt.flow
        assert retry.retries == 3

    def test_truncates_failure_output(self) -> None:
        qt = QueueTask(flow="demand", task="t")
        huge = "x" * 5000
        retry = build_retry_task(qt, huge, max_feedback_chars=100)

        # Exactly 100 chars of the failure output land in the body.
        assert "x" * 100 in retry.task
        assert "x" * 101 not in retry.task


# ---------------------------------------------------------------------------
# (2) write_retry_task
# ---------------------------------------------------------------------------


class TestWriteRetryTask:
    def test_writes_pending_reloadable_retry(self, tmp_path: Path) -> None:
        queue_dir = tmp_path / "queue"
        queue_dir.mkdir()
        qt = QueueTask(flow="demand", task="ship the widget", engine="mock", isolate=False)
        retry = build_retry_task(qt, "it failed")

        path = write_retry_task(retry, queue_dir, original_stem="job1")

        # Landed directly in queue_dir (pending), not under done/.
        assert path.parent == queue_dir
        assert not (queue_dir / "done").exists()
        assert path.suffix == ".yaml"
        # Filename signals a retry.
        assert path.name.startswith("retry-")

        # Re-loadable as a QueueTask with the right retries.
        reloaded = QueueTask.model_validate(yaml.safe_load(path.read_text()))
        assert reloaded.retries == 1
        assert reloaded.flow == "demand"

    def test_strips_leading_retry_marker_from_stem(self, tmp_path: Path) -> None:
        queue_dir = tmp_path / "queue"
        queue_dir.mkdir()
        qt = QueueTask(flow="demand", task="ship the widget", isolate=False, retries=1)
        retry = build_retry_task(qt, "failed again")

        # A retry of a retry — the leading retry-01- marker must not accrete.
        path = write_retry_task(retry, queue_dir, original_stem="retry-01-ship-abc12345")

        assert path.name.startswith("retry-02-")
        assert "retry-01" not in path.name


# ---------------------------------------------------------------------------
# (3) Drain auto-retry — end-to-end.
# ---------------------------------------------------------------------------


class TestDrainAutoRetry:
    def test_failed_task_is_reenqueued_then_succeeds(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """A failing demand drains -> retry file appears -> next pass passes."""
        repo = _build_repo(tmp_path, chore=_CHORE_FAILING, max_retries=1)
        engine = _write_file_engine("feature.txt")
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, engines: engine())
        # Non-isolated tasks run in Path.cwd(); anchor it to the repo so the
        # committing flow's clean-tree guard sees the seeded (clean) tree.
        monkeypatch.chdir(repo)

        manifest = load_manifest(repo / ".alc")
        queue_dir = repo / ".alc" / "queue"
        (queue_dir / "job1.yaml").write_text(_DEMAND_TASK)

        # Pass 1: the task fails and a retry is re-enqueued.
        results = process_queue(manifest, repo / ".alc")
        assert len(results) == 1
        assert results[0].success is False
        # Original archived to done/.
        assert (queue_dir / "done" / "job1.yaml").exists()

        # Exactly one pending retry file with retries==1 and the failure embedded.
        pending = _pending_yaml(queue_dir)
        assert len(pending) == 1
        retry_path = pending[0]
        assert retry_path.name.startswith("retry-")
        retry_qt = QueueTask.model_validate(yaml.safe_load(retry_path.read_text()))
        assert retry_qt.retries == 1
        assert "Previous attempt failed" in retry_qt.task
        # The REAL failing-stage output (not just the boilerplate header) was threaded
        # into the retry by _process_task — proves the feature glue, not a tautology.
        assert "[mock] wrote a file" in retry_qt.task

        # Flip the checks to passing, then drain again: the retry succeeds.
        (repo / ".alc" / "blueprints" / "chore.md").write_text(_CHORE_PASSING)
        _commit_all(repo, "make checks pass")
        manifest = load_manifest(repo / ".alc")

        results2 = process_queue(manifest, repo / ".alc")
        assert len(results2) == 1
        assert results2[0].success is True
        # No further retry (it passed); queue is drained.
        assert _pending_yaml(queue_dir) == []

    def test_task_at_cap_is_not_reenqueued(self, tmp_path: Path, monkeypatch) -> None:
        """A failing task already at retries==max_task_retries is NOT re-enqueued."""
        repo = _build_repo(tmp_path, chore=_CHORE_FAILING, max_retries=1)
        engine = _write_file_engine("feature.txt")
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, engines: engine())
        monkeypatch.chdir(repo)

        manifest = load_manifest(repo / ".alc")
        queue_dir = repo / ".alc" / "queue"
        # A task already at the cap (retries == max_task_retries == 1).
        capped = QueueTask(
            flow="demand", task="ship the widget", engine="mock", isolate=False, retries=1
        )
        (queue_dir / "capped.yaml").write_text(yaml.safe_dump(capped.model_dump()))

        results = process_queue(manifest, repo / ".alc")
        assert len(results) == 1
        assert results[0].success is False
        # Bounded: no retry file written.
        assert _pending_yaml(queue_dir) == []
        assert (queue_dir / "done" / "capped.yaml").exists()


# ---------------------------------------------------------------------------
# (4) Backward compat — max_task_retries unset (0) never re-enqueues.
# ---------------------------------------------------------------------------


class TestRetryBackwardCompat:
    def test_unset_writes_no_retry_file(self, tmp_path: Path, monkeypatch) -> None:
        """With max_task_retries == 0 a failed drain writes NO retry file."""
        repo = _build_repo(tmp_path, chore=_CHORE_FAILING, max_retries=0)
        engine = _write_file_engine("feature.txt")
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, engines: engine())
        monkeypatch.chdir(repo)

        manifest = load_manifest(repo / ".alc")
        assert manifest.max_task_retries == 0
        queue_dir = repo / ".alc" / "queue"
        (queue_dir / "job1.yaml").write_text(_DEMAND_TASK)

        results = process_queue(manifest, repo / ".alc")
        assert len(results) == 1
        assert results[0].success is False
        # Identical to pre-feature behavior: queue empty, only the archive remains.
        assert _pending_yaml(queue_dir) == []
        assert (queue_dir / "done" / "job1.yaml").exists()
