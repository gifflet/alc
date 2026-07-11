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
from alc.queue import (
    build_retry_task,
    outstanding_failures,
    process_queue,
    write_retry_task,
)

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

# A committing demand flow, run non-isolated (isolate:false) so the drain runs
# it in the shared workdir and the FlowRunner does its own terminal commit.
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

    def test_stamps_root_when_retrying_an_original(self, tmp_path: Path) -> None:
        """Retrying an ORIGINAL (retry_of=None) roots the lineage at its own stem."""
        queue_dir = tmp_path / "queue"
        queue_dir.mkdir()
        qt = QueueTask(flow="demand", task="ship the widget", isolate=False)
        retry = build_retry_task(qt, "it failed")

        path = write_retry_task(retry, queue_dir, original_stem="job1")

        reloaded = QueueTask.model_validate(yaml.safe_load(path.read_text()))
        assert reloaded.retry_of == "job1"

    def test_propagates_root_across_multi_level_lineage(self, tmp_path: Path) -> None:
        """Retrying a RETRY propagates the SAME root, so the chain shares one root."""
        queue_dir = tmp_path / "queue"
        queue_dir.mkdir()
        # A retry already carrying the lineage root.
        retry1 = QueueTask(
            flow="demand", task="ship the widget", isolate=False, retries=1, retry_of="job1"
        )
        retry2 = build_retry_task(retry1, "failed again")

        path = write_retry_task(retry2, queue_dir, original_stem="retry-01-ship-abc12345")

        reloaded = QueueTask.model_validate(yaml.safe_load(path.read_text()))
        # Root is the ORIGINAL's stem, not the intermediate retry's stem.
        assert reloaded.retry_of == "job1"
        assert reloaded.retries == 2


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


# ---------------------------------------------------------------------------
# (5) Manual `alc retry <stem>` — reuses build_retry_task/failure_feedback.
# ---------------------------------------------------------------------------


class TestManualRetry:
    def _archive(self, operator_layer: Path, stem: str, task: str,
                 verdict: str, success: bool = False) -> None:
        from alc.models import FlowReport, RunReport, Scorecard

        manifest = load_manifest(operator_layer)
        done = operator_layer.parent / manifest.queue_dir / "done"
        done.mkdir(parents=True, exist_ok=True)
        (done / f"{stem}.yaml").write_text(
            yaml.safe_dump({"flow": "demand", "task": task, "isolate": False})
        )
        sc = Scorecard(span=0, passes=0, streak=0, touch=0)
        report = FlowReport(
            flow="demand", engine="mock", success=success,
            stages=[RunReport(blueprint="qa", engine="mock", success=success,
                              attempts=[], scorecard=sc, output_text=verdict)],
            scorecard=sc,
        )
        (done / f"{stem}.report.json").write_text(report.model_dump_json(indent=2))

    def test_reenqueues_failed_task_with_feedback(self, operator_layer, monkeypatch) -> None:
        import argparse

        from alc.cli import cmd_retry

        stem = "plan-001-sombras-d1d54fe1"
        self._archive(operator_layer, stem, "Add mineral shadows",
                      "VERDICT: FAIL — contrast too low on dark mode")
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_retry(argparse.Namespace(stem=stem, all=False)) == 0

        manifest = load_manifest(operator_layer)
        queue_dir = operator_layer.parent / manifest.queue_dir
        pending = sorted(queue_dir.glob("*.yaml"))
        assert len(pending) == 1
        qt = QueueTask.model_validate(yaml.safe_load(pending[0].read_text()))
        assert qt.retries == 1
        assert qt.flow == "demand"
        assert "Add mineral shadows" in qt.task
        assert "VERDICT: FAIL — contrast too low on dark mode" in qt.task

    def test_stem_with_extension_is_tolerated(self, operator_layer, monkeypatch) -> None:
        import argparse

        from alc.cli import cmd_retry

        stem = "demand-x"
        self._archive(operator_layer, stem, "t", "why it failed")
        monkeypatch.chdir(operator_layer.parent)
        # Passing the archived report filename is stripped to the stem.
        assert cmd_retry(argparse.Namespace(stem=f"{stem}.report.json", all=False)) == 0

    def test_succeeded_task_refuses(self, operator_layer, monkeypatch, capsys) -> None:
        import argparse

        from alc.cli import cmd_retry

        stem = "ok"
        self._archive(operator_layer, stem, "t", "VERDICT: PASS", success=True)
        monkeypatch.chdir(operator_layer.parent)
        assert cmd_retry(argparse.Namespace(stem=stem, all=False)) == 1
        assert "nothing to retry" in capsys.readouterr().err

    def test_missing_archive_errors(self, operator_layer, monkeypatch, capsys) -> None:
        import argparse

        from alc.cli import cmd_retry

        monkeypatch.chdir(operator_layer.parent)
        assert cmd_retry(argparse.Namespace(stem="nope", all=False)) == 1
        assert "no archived task" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# (6) outstanding_failures — the retryable-list query with lineage resolution.
# ---------------------------------------------------------------------------


def _archive_task(
    done_dir: Path,
    stem: str,
    task: str,
    verdict: str,
    *,
    success: bool = False,
    retries: int = 0,
    retry_of: str | None = None,
    checks: tuple[str, ...] = ("verdict-pass",),
) -> None:
    """Write a done/<stem>.yaml + done/<stem>.report.json pair for a test archive."""
    from alc.models import AttemptRecord, FlowReport, RunReport, Scorecard

    done_dir.mkdir(parents=True, exist_ok=True)
    qt = QueueTask(
        flow="demand", task=task, isolate=False, retries=retries, retry_of=retry_of
    )
    (done_dir / f"{stem}.yaml").write_text(yaml.safe_dump(qt.model_dump()))
    sc = Scorecard(span=0, passes=0, streak=0, touch=0)
    failed = [] if success else list(checks)
    report = FlowReport(
        flow="demand", engine="mock", success=success,
        stages=[RunReport(
            blueprint="qa", engine="mock", success=success,
            attempts=[AttemptRecord(index=0, engine_ok=True, failed_checks=failed)],
            scorecard=sc, output_text=verdict,
        )],
        scorecard=sc,
    )
    (done_dir / f"{stem}.report.json").write_text(report.model_dump_json(indent=2))


class TestOutstandingFailures:
    def test_lone_failure_is_listed_once(self, tmp_path: Path) -> None:
        done = tmp_path / "done"
        _archive_task(done, "job1", "Add mineral shadows",
                      "line one\nVERDICT: FAIL — contrast too low", retries=0)

        failures = outstanding_failures(done)
        assert len(failures) == 1
        entry = failures[0]
        assert entry.stem == "job1"
        assert entry.title == "Add mineral shadows"
        # reason is the structured failing stage + check(s), not free-text prose.
        assert entry.reason == "failed at qa: check(s) verdict-pass"
        assert entry.retries == 0

    def test_resolved_lineage_is_not_listed(self, tmp_path: Path) -> None:
        done = tmp_path / "done"
        # An original failure, then a retry (same root) that SUCCEEDED.
        _archive_task(done, "job1", "Add shadows", "VERDICT: FAIL", retries=0)
        _archive_task(done, "retry-01-add-shadows-abc12345", "Add shadows",
                      "VERDICT: PASS", success=True, retries=1, retry_of="job1")

        assert outstanding_failures(done) == []

    def test_two_independent_roots_yield_two_entries(self, tmp_path: Path) -> None:
        done = tmp_path / "done"
        _archive_task(done, "job1", "First task", "boom one", retries=0)
        _archive_task(done, "job2", "Second task", "boom two", retries=0)

        failures = outstanding_failures(done)
        # Two distinct roots; order is by recency (asserted separately), so compare sorted.
        assert sorted(e.stem for e in failures) == ["job1", "job2"]

    def test_sorted_by_recency_most_recent_first(self, tmp_path: Path) -> None:
        import os

        done = tmp_path / "done"
        _archive_task(done, "older", "Old task", "boom", retries=0)
        _archive_task(done, "newer", "New task", "boom", retries=0)
        # Force distinct mtimes: 'newer' more recently failed than 'older'.
        os.utime(done / "older.report.json", (1000, 1000))
        os.utime(done / "newer.report.json", (2000, 2000))

        assert [e.stem for e in outstanding_failures(done)] == ["newer", "older"]

    def test_latest_attempt_per_root_is_returned(self, tmp_path: Path) -> None:
        done = tmp_path / "done"
        # Same lineage (root job1), two failed attempts — the highest-retries wins.
        _archive_task(done, "job1", "Add shadows", "first failure",
                      retries=0, checks=("verdict-pass",))
        _archive_task(done, "retry-01-add-shadows-abc12345", "Add shadows",
                      "latest failure", retries=2, retry_of="job1", checks=("typecheck",))

        failures = outstanding_failures(done)
        assert len(failures) == 1
        assert failures[0].stem == "retry-01-add-shadows-abc12345"
        assert failures[0].retries == 2
        # The reason comes from the LATEST attempt's report (its check), not the first.
        assert failures[0].reason == "failed at qa: check(s) typecheck"

    def test_absent_or_empty_done_dir_is_empty(self, tmp_path: Path) -> None:
        assert outstanding_failures(tmp_path / "missing") == []
        empty = tmp_path / "done"
        empty.mkdir()
        assert outstanding_failures(empty) == []


# ---------------------------------------------------------------------------
# (7) `alc retry` with no stem — list / --all paths.
# ---------------------------------------------------------------------------


class TestRetryListAndAll:
    def test_no_stem_lists_outstanding_failures(
        self, operator_layer, monkeypatch, capsys
    ) -> None:
        import argparse

        from alc.cli import cmd_retry

        manifest = load_manifest(operator_layer)
        done = operator_layer.parent / manifest.queue_dir / "done"
        _archive_task(done, "plan-001-sombras-d1d54fe1", "Add mineral shadows",
                      "VERDICT: FAIL — contrast too low")
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_retry(argparse.Namespace(stem=None, all=False)) == 0
        out = capsys.readouterr().out
        assert "plan-001-sombras-d1d54fe1" in out
        assert "Add mineral shadows" in out
        assert "alc retry --all" in out

    def test_all_reenqueues_every_outstanding_failure(
        self, operator_layer, monkeypatch
    ) -> None:
        import argparse

        from alc.cli import cmd_retry

        manifest = load_manifest(operator_layer)
        done = operator_layer.parent / manifest.queue_dir / "done"
        _archive_task(done, "job1", "First task", "boom one")
        _archive_task(done, "job2", "Second task", "boom two")
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_retry(argparse.Namespace(stem=None, all=True)) == 0

        queue_dir = operator_layer.parent / manifest.queue_dir
        pending = _pending_yaml(queue_dir)
        assert len(pending) == 2
        assert all(p.name.startswith("retry-") for p in pending)

    def test_no_failures_prints_message(
        self, operator_layer, monkeypatch, capsys
    ) -> None:
        import argparse

        from alc.cli import cmd_retry

        monkeypatch.chdir(operator_layer.parent)
        assert cmd_retry(argparse.Namespace(stem=None, all=False)) == 0
        assert "No failed tasks to retry." in capsys.readouterr().out

    def test_json_output_is_machine_readable(
        self, operator_layer, monkeypatch, capsys
    ) -> None:
        import argparse
        import json as _json

        from alc.cli import cmd_retry

        manifest = load_manifest(operator_layer)
        done = operator_layer.parent / manifest.queue_dir / "done"
        _archive_task(done, "plan-001-sombras-d1d54fe1", "Add mineral shadows",
                      "VERDICT: FAIL", checks=("verdict-pass",))
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_retry(argparse.Namespace(stem=None, all=False, json=True)) == 0
        data = _json.loads(capsys.readouterr().out)
        assert isinstance(data, list) and len(data) == 1
        assert data[0] == {
            "stem": "plan-001-sombras-d1d54fe1",
            "title": "Add mineral shadows",
            "reason": "failed at qa: check(s) verdict-pass",
            "retries": 0,
        }

    def test_json_output_empty_is_a_json_array(
        self, operator_layer, monkeypatch, capsys
    ) -> None:
        import argparse
        import json as _json

        from alc.cli import cmd_retry

        monkeypatch.chdir(operator_layer.parent)
        assert cmd_retry(argparse.Namespace(stem=None, all=False, json=True)) == 0
        assert _json.loads(capsys.readouterr().out) == []
