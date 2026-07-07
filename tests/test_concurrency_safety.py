# test_concurrency_safety.py — Hermetic tests for queue concurrency safety.
#
# Coverage:
#   (a) cmd_tick rejects --concurrency < 1 before touching the filesystem.
#   (b) _partition_tasks correctly classifies tasks as parallel or serial.
#   (c) Integration: 3 non-isolated tasks + max_workers=3 -> all archived in order.
from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from alc.cli import cmd_tick
from alc.intake import load_manifest
from alc.queue import _partition_tasks, process_queue


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TASK_ISOLATE_TRUE = """\
flow: ship
task: "task-{index}"
engine: mock
isolate: true
"""

_TASK_ISOLATE_FALSE = """\
flow: ship
task: "task-{index}"
engine: mock
isolate: false
"""


def _write_task(queue_dir: Path, stem: str, yaml_text: str) -> Path:
    """Write a task YAML file and return the path."""
    path = queue_dir / f"{stem}.yaml"
    path.write_text(yaml_text)
    return path


# ---------------------------------------------------------------------------
# (a) cmd_tick rejects --concurrency < 1
# ---------------------------------------------------------------------------


class TestCmdTickConcurrencyValidation:
    def test_zero_concurrency_returns_1_with_error(
        self, operator_layer: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """--concurrency 0 must print an error to stderr and return 1."""
        monkeypatch.chdir(operator_layer.parent)

        args = argparse.Namespace(concurrency=0)
        result = cmd_tick(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "[ERROR] --concurrency must be >= 1" in captured.err

    def test_negative_concurrency_returns_1_with_error(
        self, operator_layer: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """--concurrency -5 must print an error to stderr and return 1."""
        monkeypatch.chdir(operator_layer.parent)

        args = argparse.Namespace(concurrency=-5)
        result = cmd_tick(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "[ERROR] --concurrency must be >= 1" in captured.err

    def test_zero_concurrency_does_not_touch_queue(
        self, operator_layer: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """With concurrency=0 no lock is acquired and no queue processing occurs."""
        monkeypatch.chdir(operator_layer.parent)

        # Place a task file in the queue; it must NOT be processed.
        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        task_path = queue_dir / "t1.yaml"
        task_path.write_text(_TASK_ISOLATE_FALSE.format(index=0))

        args = argparse.Namespace(concurrency=0)
        cmd_tick(args)

        # The task file must still be in the queue (not moved to done/).
        assert task_path.exists()
        assert not (queue_dir / "done" / "t1.yaml").exists()


# ---------------------------------------------------------------------------
# (b) Unit tests for _partition_tasks
# ---------------------------------------------------------------------------


class TestPartitionTasks:
    def test_isolate_true_and_git_goes_to_parallel(self, tmp_path: Path) -> None:
        """isolate:true with is_git=True -> parallel bucket."""
        task = _write_task(tmp_path, "p1", _TASK_ISOLATE_TRUE.format(index=0))
        parallel, serial = _partition_tasks([task], is_git=True)
        assert parallel == [task]
        assert serial == []

    def test_isolate_false_goes_to_serial(self, tmp_path: Path) -> None:
        """isolate:false with is_git=True -> serial bucket."""
        task = _write_task(tmp_path, "s1", _TASK_ISOLATE_FALSE.format(index=0))
        parallel, serial = _partition_tasks([task], is_git=True)
        assert parallel == []
        assert serial == [task]

    def test_isolate_true_but_non_git_goes_to_serial(self, tmp_path: Path) -> None:
        """isolate:true but is_git=False -> serial (worktree not possible)."""
        task = _write_task(tmp_path, "s2", _TASK_ISOLATE_TRUE.format(index=0))
        parallel, serial = _partition_tasks([task], is_git=False)
        assert parallel == []
        assert serial == [task]

    def test_mixed_tasks_split_correctly(self, tmp_path: Path) -> None:
        """Mixed isolate flags with is_git=True -> each goes to the right bucket."""
        p1 = _write_task(tmp_path, "a", _TASK_ISOLATE_TRUE.format(index=0))
        s1 = _write_task(tmp_path, "b", _TASK_ISOLATE_FALSE.format(index=1))
        p2 = _write_task(tmp_path, "c", _TASK_ISOLATE_TRUE.format(index=2))

        parallel, serial = _partition_tasks([p1, s1, p2], is_git=True)

        assert parallel == [p1, p2]
        assert serial == [s1]

    def test_order_preserved_within_each_bucket(self, tmp_path: Path) -> None:
        """Relative order is maintained inside both the parallel and serial lists."""
        tasks = [
            _write_task(tmp_path, f"t{i}", _TASK_ISOLATE_FALSE.format(index=i))
            for i in range(4)
        ]
        parallel, serial = _partition_tasks(tasks, is_git=False)
        assert parallel == []
        assert serial == tasks  # original order preserved

    def test_invalid_yaml_treated_as_serial(self, tmp_path: Path) -> None:
        """An unreadable/invalid task file falls into the serial bucket."""
        bad = tmp_path / "bad.yaml"
        bad.write_text("flow: [unclosed")
        parallel, serial = _partition_tasks([bad], is_git=True)
        assert parallel == []
        assert serial == [bad]


# ---------------------------------------------------------------------------
# (c) Integration: 3 non-isolated tasks, max_workers=3 -> all archived in order
# ---------------------------------------------------------------------------


class TestProcessQueueSerialDemotionIntegration:
    def test_three_non_isolated_tasks_processed_in_order(
        self, operator_layer: Path, capsys
    ) -> None:
        """3 isolate:false tasks with max_workers=3 run serially and are archived."""
        manifest = load_manifest(operator_layer)

        # operator_layer fixture lives in a plain tmp dir (not a git repo).
        # All 3 tasks have isolate:false, so all must be demoted to serial.
        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        for i in range(3):
            _write_task(queue_dir, f"t{i}", _TASK_ISOLATE_FALSE.format(index=i))

        results = process_queue(manifest, operator_layer, max_workers=3)

        # All 3 tasks were processed and succeeded.
        assert len(results) == 3
        assert all(r.success for r in results)

        # Original pending order is preserved (sorted: t0, t1, t2).
        assert [r.task_file for r in results] == ["t0.yaml", "t1.yaml", "t2.yaml"]

        # Each task is archived in done/.
        done_dir = queue_dir / "done"
        for i in range(3):
            assert (done_dir / f"t{i}.yaml").exists(), f"t{i}.yaml not in done/"
            assert (done_dir / f"t{i}.report.json").exists(), f"t{i}.report.json missing"
            assert not (queue_dir / f"t{i}.yaml").exists(), f"t{i}.yaml still in queue"

        # The demotion note was printed to stderr.
        captured = capsys.readouterr()
        assert "3 non-isolated task(s) will run serially" in captured.err

    def test_serial_path_emits_no_demotion_note(
        self, operator_layer: Path, capsys
    ) -> None:
        """The serial drain path (max_workers=1) never prints the demotion notice."""
        manifest = load_manifest(operator_layer)
        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        for i in range(2):
            _write_task(queue_dir, f"s{i}", _TASK_ISOLATE_FALSE.format(index=i))

        # max_workers=1 takes the serial code path, which bypasses _partition_tasks
        # entirely — the demotion notice must never appear regardless of isolate flags.
        results = process_queue(manifest, operator_layer, max_workers=1)

        assert len(results) == 2
        assert all(r.success for r in results)
        captured = capsys.readouterr()
        assert "non-isolated" not in captured.err
