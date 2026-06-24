# test_queue.py — Hermetic tests for Unattended Mode: process_queue.
# All tests use the mock engine and isolate: false so no git repository is needed.
from __future__ import annotations

import json
from pathlib import Path

import pytest

from alc.intake import load_manifest
from alc.queue import process_queue


_TASK_YAML = """\
flow: ship
task: "tidy"
engine: mock
isolate: false
"""


class TestProcessQueueRunsAndArchives:
    def test_process_queue_runs_and_archives(self, operator_layer: Path) -> None:
        """A pending task is executed and moved to done/ with its Gate report."""
        manifest = load_manifest(operator_layer)

        # Create queue dir and drop one task file.
        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "t1.yaml").write_text(_TASK_YAML)

        results = process_queue(manifest, operator_layer)

        # One result, successful, referencing the "ship" flow.
        assert len(results) == 1
        result = results[0]
        assert result.success is True
        assert result.flow == "ship"

        # Task file must have moved out of the top-level queue dir.
        assert not (queue_dir / "t1.yaml").exists()

        # Task file must now be inside done/.
        done_dir = queue_dir / "done"
        assert (done_dir / "t1.yaml").exists()

        # Gate report must exist and be valid JSON with the expected flow name.
        report_path = done_dir / "t1.report.json"
        assert report_path.exists()
        raw = json.loads(report_path.read_text())
        assert raw["flow"] == "ship"
        assert raw["success"] is True


class TestProcessQueueEmptyWhenNoDir:
    def test_process_queue_empty_when_no_dir(self, operator_layer: Path) -> None:
        """process_queue returns [] when the queue directory does not exist."""
        manifest = load_manifest(operator_layer)

        # Ensure the queue dir is absent.
        queue_dir = operator_layer / "queue"
        assert not queue_dir.exists()

        results = process_queue(manifest, operator_layer)
        assert results == []


class TestProcessQueueSkipsAlreadyProcessed:
    def test_process_queue_skips_already_processed(self, operator_layer: Path) -> None:
        """A second tick call returns [] because the task was archived on the first."""
        manifest = load_manifest(operator_layer)

        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "t1.yaml").write_text(_TASK_YAML)

        # First pass: process the task.
        first = process_queue(manifest, operator_layer)
        assert len(first) == 1

        # Second pass: no pending tasks remain.
        second = process_queue(manifest, operator_layer)
        assert second == []
