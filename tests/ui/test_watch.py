# test_watch.py — File-watching classification and run-log tailing.
#
# The watch logic is split so it is covered DETERMINISTICALLY without watchfiles:
# classify_change() is a pure function and Watcher._handle/_emit_run_lines are
# driven directly. A real watchfiles end-to-end test was intentionally left out:
# it proved timing-flaky in this environment (the OS notification is not
# guaranteed within a bounded wait), so the plan's "só se for estável" clause
# applies — the wiring that feeds these functions from awatch is exercised
# manually via `alc ui`.
from __future__ import annotations

from pathlib import Path

import pytest

from alc.ui.repostatus import RepoStatus, RepoStatusTracker
from alc.ui.watch import Watcher, classify_change, is_repo_watch_path


class _RecordingBus:
    """Minimal bus stub capturing every published message."""

    def __init__(self) -> None:
        self.messages: list[dict] = []

    def publish(self, message: dict) -> None:
        self.messages.append(message)


def _alc(tmp_path: Path) -> Path:
    alc = tmp_path / ".alc"
    alc.mkdir(parents=True, exist_ok=True)
    return alc


class TestClassifyChange:
    def test_manifest(self, tmp_path: Path) -> None:
        alc = _alc(tmp_path)
        assert classify_change(alc, alc / "manifest.yaml") == {
            "type": "config_changed",
            "resource": "manifest",
        }

    def test_blueprint(self, tmp_path: Path) -> None:
        alc = _alc(tmp_path)
        assert classify_change(alc, alc / "blueprints" / "chore.md") == {
            "type": "config_changed",
            "resource": "blueprints",
        }

    def test_queue_pending(self, tmp_path: Path) -> None:
        alc = _alc(tmp_path)
        assert classify_change(alc, alc / "queue" / "job.yaml") == {"type": "queue_changed"}

    def test_queue_done_report(self, tmp_path: Path) -> None:
        alc = _alc(tmp_path)
        result = classify_change(alc, alc / "queue" / "done" / "job.report.json")
        assert result == {"type": "report_added", "stem": "job"}

    def test_run_log(self, tmp_path: Path) -> None:
        alc = _alc(tmp_path)
        result = classify_change(alc, alc / "runs" / "20250101T000000-run-x-abc123.jsonl")
        assert result == {"type": "run", "stem": "20250101T000000-run-x-abc123"}

    def test_loop_state(self, tmp_path: Path) -> None:
        alc = _alc(tmp_path)
        assert classify_change(alc, alc / "loops" / "deliver.state.json") == {
            "type": "loop_changed",
            "name": "deliver",
        }

    def test_signal(self, tmp_path: Path) -> None:
        alc = _alc(tmp_path)
        assert classify_change(alc, alc / "signals" / "error-x-abc123.json") == {
            "type": "signals_changed",
        }

    def test_run_configs(self, tmp_path: Path) -> None:
        alc = _alc(tmp_path)
        assert classify_change(alc, alc / "ui" / "run-configs.json") == {
            "type": "run_configs_changed",
        }

    def test_unrelated_path_is_none(self, tmp_path: Path) -> None:
        alc = _alc(tmp_path)
        assert classify_change(alc, tmp_path / "README.md") is None
        assert classify_change(alc, alc / "bundles" / "x.jsonl") is None
        assert classify_change(alc, alc / "ui" / "layout.json") is None


class TestRunTailing:
    def test_emit_only_new_lines(self, tmp_path: Path) -> None:
        bus = _RecordingBus()
        watcher = Watcher(registry=None, bus=bus)  # type: ignore[arg-type]
        runs = _alc(tmp_path) / "runs"
        runs.mkdir()
        log = runs / "20250101T000000-run-x-abc123.jsonl"
        log.write_text('{"event": "act_started", "attempt": 1}\n')

        watcher._emit_run_lines("p1", log)
        assert len(bus.messages) == 1
        assert bus.messages[0]["type"] == "run_event"
        assert bus.messages[0]["event"]["event"] == "act_started"

        with log.open("a") as fh:
            fh.write('{"event": "act_finished", "attempt": 1, "ok": true}\n')
        watcher._emit_run_lines("p1", log)
        assert len(bus.messages) == 2
        assert bus.messages[1]["event"]["event"] == "act_finished"

    def test_handle_classifies_and_tags_project(self, tmp_path: Path) -> None:
        bus = _RecordingBus()
        watcher = Watcher(registry=None, bus=bus)  # type: ignore[arg-type]
        alc = _alc(tmp_path)
        blueprint = alc / "blueprints" / "chore.md"
        blueprint.parent.mkdir(parents=True)
        blueprint.write_text("x")

        watcher._handle(blueprint, {alc.resolve(): "p1"}, {tmp_path.resolve(): "p1"})
        assert bus.messages[-1] == {
            "type": "config_changed",
            "resource": "blueprints",
            "project_id": "p1",
        }


# ---------------------------------------------------------------------------
# is_repo_watch_path — the PYTHON-side awatch filter (pure, unit-tested like
# classify_change). Note: watchfiles filters python-side; the Rust watcher still
# walks the whole tree recursively, so this only trims what reaches our handler.
# ---------------------------------------------------------------------------


class TestIsRepoWatchPath:
    @pytest.mark.parametrize(
        "path",
        [
            # A working-tree edit — the whole point of watching the root.
            "/proj/src/app.py",
            # The existing .alc/ message stream MUST survive the new filter
            # (regression pin — never silently filter control-plane events).
            "/proj/.alc/queue/job.yaml",
            "/proj/.alc/loops/deliver.state.json",
            # The precise .git/ entries a commit/stash/checkout touches.
            "/proj/.git/HEAD",
            "/proj/.git/ORIG_HEAD",
            "/proj/.git/MERGE_HEAD",
            "/proj/.git/FETCH_HEAD",
            "/proj/.git/index",
            "/proj/.git/packed-refs",
            "/proj/.git/refs/heads/main",
            "/proj/.git/refs/tags/v1",
        ],
    )
    def test_allowed(self, path: str) -> None:
        assert is_repo_watch_path(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            # Noisy .git internals a status read does not care about.
            "/proj/.git/objects/ab/cdef",
            "/proj/.git/logs/HEAD",
            "/proj/.git/hooks/pre-commit",
            # .lock churn is dropped — the rename to the final name still fires.
            "/proj/.git/index.lock",
            "/proj/.git/refs/heads/main.lock",
            # Pragmatic ignore set — a build/dep dir is never a repo-status signal.
            "/proj/node_modules/x/index.js",
            "/proj/.venv/lib/python/site.py",
            "/proj/dist/bundle.js",
            "/proj/build/out.o",
            "/proj/__pycache__/mod.cpython-312.pyc",
            "/proj/.pytest_cache/v/cache",
        ],
    )
    def test_rejected(self, path: str) -> None:
        assert is_repo_watch_path(path) is False


# ---------------------------------------------------------------------------
# RepoStatusTracker — debounce + recompute + emit-on-flip. Driven directly with
# a RecordingBus, an injected fake reader, and an injected clock (no real sleeps).
# ---------------------------------------------------------------------------


class _Clock:
    """A hand-cranked monotonic clock so debounce is tested without sleeping."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class TestRepoStatusTracker:
    def test_mark_then_flush_past_debounce_publishes_status(self) -> None:
        from dataclasses import asdict

        bus = _RecordingBus()
        clock = _Clock()
        status = RepoStatus(available=True, branch="main", dirty=True, untracked=1)
        tracker = RepoStatusTracker(
            bus, read_status=lambda _root: status, debounce_s=0.4, now=clock
        )
        roots = {"p1": Path("/proj")}

        tracker.mark("p1")  # anchored at t=0
        clock.t = 0.5  # past the debounce window
        tracker.flush(roots)

        assert bus.messages == [
            {"type": "worktree_changed", "project_id": "p1", "status": asdict(status)}
        ]

    def test_same_status_does_not_republish_but_flip_does(self) -> None:
        bus = _RecordingBus()
        clock = _Clock()
        box = {"status": RepoStatus(available=True, branch="main", dirty=False)}
        tracker = RepoStatusTracker(
            bus, read_status=lambda _root: box["status"], debounce_s=0.4, now=clock
        )
        roots = {"p1": Path("/proj")}

        tracker.mark("p1")
        clock.t = 0.5
        tracker.flush(roots)
        assert len(bus.messages) == 1  # cache-miss first publish

        # Same status again -> emit-on-flip suppresses a duplicate.
        tracker.mark("p1")
        clock.t = 1.0
        tracker.flush(roots)
        assert len(bus.messages) == 1

        # Now it flips (a commit cleaned the tree) -> one publish.
        box["status"] = RepoStatus(available=True, branch="main", dirty=True)
        tracker.mark("p1")
        clock.t = 1.5
        tracker.flush(roots)
        assert len(bus.messages) == 2

    def test_two_projects_are_independent(self) -> None:
        bus = _RecordingBus()
        clock = _Clock()
        statuses = {
            Path("/a"): RepoStatus(available=True, branch="a"),
            Path("/b"): RepoStatus(available=True, branch="b"),
        }
        tracker = RepoStatusTracker(
            bus, read_status=lambda root: statuses[root], debounce_s=0.4, now=clock
        )
        roots = {"pa": Path("/a"), "pb": Path("/b")}

        tracker.mark("pa")
        tracker.mark("pb")
        clock.t = 0.5
        tracker.flush(roots)

        pids = sorted(m["project_id"] for m in bus.messages)
        assert pids == ["pa", "pb"]

    def test_debounce_coalesces_a_burst_into_one_recompute(self) -> None:
        bus = _RecordingBus()
        clock = _Clock()
        calls = {"n": 0}

        def reader(_root: Path) -> RepoStatus:
            calls["n"] += 1
            return RepoStatus(available=True, branch="main")

        tracker = RepoStatusTracker(bus, read_status=reader, debounce_s=0.4, now=clock)
        roots = {"p1": Path("/proj")}

        tracker.mark("p1")  # first event anchors the window at t=0
        clock.t = 0.2
        tracker.mark("p1")  # still in the window — setdefault keeps t=0

        # Not yet due -> flush is a no-op, nothing recomputed, still pending.
        tracker.flush(roots)
        assert calls["n"] == 0

        clock.t = 0.5  # window elapsed
        tracker.flush(roots)
        assert calls["n"] == 1  # exactly ONE recompute for the whole burst

    def test_prune_drops_removed_projects(self) -> None:
        bus = _RecordingBus()
        clock = _Clock()
        tracker = RepoStatusTracker(
            bus,
            read_status=lambda _root: RepoStatus(available=True),
            debounce_s=0.4,
            now=clock,
        )
        roots = {"p1": Path("/proj")}
        tracker.mark("p1")
        clock.t = 0.5
        tracker.flush(roots)  # populates _last["p1"]

        tracker.mark("p1")  # a fresh pending mark
        tracker.prune({"other"})  # p1 is gone from the registry

        assert "p1" not in tracker._pending
        assert "p1" not in tracker._last


# ---------------------------------------------------------------------------
# Watcher._handle — the tracker-marking split from the .alc classification.
# ---------------------------------------------------------------------------


class TestHandleTrackerRouting:
    def test_non_alc_path_under_root_marks_the_tracker(self, tmp_path: Path) -> None:
        bus = _RecordingBus()
        watcher = Watcher(registry=None, bus=bus)  # type: ignore[arg-type]
        alc = _alc(tmp_path)
        src = tmp_path / "src" / "app.py"
        src.parent.mkdir(parents=True)
        src.write_text("x")

        watcher._handle(src, {alc.resolve(): "p1"}, {tmp_path.resolve(): "p1"})

        # A working-tree edit marks the tracker for a debounced status read; it
        # publishes NOTHING directly (the tracker decides that on flush).
        assert "p1" in watcher._tracker._pending
        assert bus.messages == []

    def test_alc_path_classifies_and_does_not_mark(self, tmp_path: Path) -> None:
        bus = _RecordingBus()
        watcher = Watcher(registry=None, bus=bus)  # type: ignore[arg-type]
        alc = _alc(tmp_path)
        queue_file = alc / "queue" / "job.yaml"
        queue_file.parent.mkdir(parents=True)
        queue_file.write_text("x")

        watcher._handle(queue_file, {alc.resolve(): "p1"}, {tmp_path.resolve(): "p1"})

        # The .alc/ stream classifies as before AND never marks the tracker (a
        # commit that also touches .git/index marks it via that path instead).
        assert bus.messages[-1]["type"] == "queue_changed"
        assert watcher._tracker._pending == {}
