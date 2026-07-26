# test_runs.py — Hermetic tests for the core run-log readers.
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from alc.runs import list_runs, read_run


def _write_run(runs_dir: Path, stem: str, events: list[str]) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    body = "".join(f'{{"event": "{e}"}}\n' for e in events)
    path = runs_dir / f"{stem}.jsonl"
    path.write_text(body)
    return path


class TestListRunsEmpty:
    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        assert list_runs(tmp_path / "runs", stale_after=1800) == {"runs": [], "total": 0}


class TestListRunsFinished:
    """The `finished` flag matches the run detail view's buildTimeline: a
    flow/task run's inner `mandate_finished` is NOT terminal — the run stays
    live until `flow_finished` / `task_finished`; a bare mandate run closes at
    its own `mandate_finished`."""

    def test_finished_flag_matches_run_kind(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _write_run(
            runs_dir,
            "20260101T000000-flow-live-aaaaaa",
            ["flow_started", "stage_started", "mandate_started", "mandate_finished"],
        )
        _write_run(
            runs_dir,
            "20260101T000001-flow-done-bbbbbb",
            ["flow_started", "mandate_started", "mandate_finished", "flow_finished"],
        )
        _write_run(
            runs_dir,
            "20260101T000002-task-done-cccccc",
            ["task_started", "mandate_started", "mandate_finished", "task_finished"],
        )
        _write_run(
            runs_dir, "20260101T000003-run-bare-dddddd", ["mandate_started", "mandate_finished"]
        )

        runs = list_runs(runs_dir, stale_after=1800)["runs"]
        finished = {r["stem"]: r["finished"] for r in runs}

        assert finished["20260101T000000-flow-live-aaaaaa"] is False
        assert finished["20260101T000001-flow-done-bbbbbb"] is True
        assert finished["20260101T000002-task-done-cccccc"] is True
        assert finished["20260101T000003-run-bare-dddddd"] is True

    def test_run_aborted_is_terminal_for_every_kind(self, tmp_path: Path) -> None:
        """An interrupted run's `run_aborted` closes it — flow, task, or bare mandate —
        even without the kind's usual wrapper terminal."""
        runs_dir = tmp_path / "runs"
        _write_run(
            runs_dir,
            "20260101T000000-flow-killed-aaaaaa",
            ["flow_started", "stage_started", "mandate_started", "run_aborted"],
        )
        _write_run(
            runs_dir,
            "20260101T000001-task-killed-bbbbbb",
            ["task_started", "mandate_started", "run_aborted"],
        )
        _write_run(
            runs_dir,
            "20260101T000002-run-killed-cccccc",
            ["mandate_started", "run_aborted"],
        )

        runs = list_runs(runs_dir, stale_after=1800)["runs"]
        finished = {r["stem"]: r["finished"] for r in runs}

        assert finished["20260101T000000-flow-killed-aaaaaa"] is True
        assert finished["20260101T000001-task-killed-bbbbbb"] is True
        assert finished["20260101T000002-run-killed-cccccc"] is True

    def test_kind_extracted_from_stem(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _write_run(runs_dir, "20260101T000000-flow-live-aaaaaa", ["flow_started"])

        runs = list_runs(runs_dir, stale_after=1800)["runs"]
        assert runs[0]["kind"] == "flow"


class TestListRunsStale:
    def test_stale_flag_marks_an_interrupted_run(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        interrupted = _write_run(
            runs_dir,
            "20260101T000010-flow-interrupted-eeeeee",
            ["flow_started", "stage_started", "mandate_started"],
        )
        day_ago = time.time() - 24 * 3600
        os.utime(interrupted, (day_ago, day_ago))
        _write_run(runs_dir, "20260101T000011-flow-live-ffffff", ["flow_started", "mandate_started"])
        _write_run(runs_dir, "20260101T000012-flow-done-gggggg", ["flow_started", "flow_finished"])

        by = {r["stem"]: r for r in list_runs(runs_dir, stale_after=1800)["runs"]}
        assert by["20260101T000010-flow-interrupted-eeeeee"]["stale"] is True
        assert by["20260101T000010-flow-interrupted-eeeeee"]["finished"] is False
        assert by["20260101T000011-flow-live-ffffff"]["stale"] is False
        assert by["20260101T000012-flow-done-gggggg"]["stale"] is False


class TestListRunsPagination:
    def test_limit_and_offset_page_through_newest_first(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        for i in range(3):
            _write_run(runs_dir, f"2026010{i}T000000-run-x-{i:06d}", ["mandate_finished"])
            time.sleep(0.01)

        result = list_runs(runs_dir, stale_after=1800, limit=1, offset=1)
        assert result["total"] == 3
        assert len(result["runs"]) == 1


class TestReadRunMissing:
    def test_raises_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            read_run(tmp_path / "runs", "ghost", stale_after=1800)


class TestReadRunEvents:
    def test_returns_events_and_next_offset(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _write_run(runs_dir, "20260101T000000-run-x-aaaaaa", ["a", "b", "c"])

        result = read_run(runs_dir, "20260101T000000-run-x-aaaaaa", stale_after=1800)
        assert [e["event"] for e in result["events"]] == ["a", "b", "c"]
        assert result["next_offset"] == 3

    def test_offset_returns_only_new_lines(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _write_run(runs_dir, "20260101T000000-run-x-aaaaaa", ["a", "b", "c"])

        result = read_run(runs_dir, "20260101T000000-run-x-aaaaaa", stale_after=1800, offset=1)
        assert [e["event"] for e in result["events"]] == ["b", "c"]

    def test_stale_flag_reflects_finished_and_age(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        path = _write_run(runs_dir, "20260101T000000-run-x-aaaaaa", ["mandate_started"])
        day_ago = time.time() - 24 * 3600
        os.utime(path, (day_ago, day_ago))

        result = read_run(runs_dir, "20260101T000000-run-x-aaaaaa", stale_after=1800)
        assert result["stale"] is True
