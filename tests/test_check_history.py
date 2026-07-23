# test_check_history.py — Hermetic tests for `alc checks history [--json]`
# (roadmap-phase-3.md T10): a sibling action to `audit` that aggregates the run
# logs' `check_finished` events into per-check pass-rate, mean duration, and a
# flake score. Pure/read-only — writes JSONL fixtures directly rather than
# running real mandates, mirroring how `alc audit` (test_audit.py) is tested.
from __future__ import annotations

import argparse
import json
from pathlib import Path

from alc.checks import CheckHistory, check_history
from alc.cli import cmd_checks


def _write_log(runs_dir: Path, stem: str, events: list[dict]) -> Path:
    """Write one run-log .jsonl file with the given event dicts, one per line."""
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"{stem}.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return path


def _check_finished(name: str, passed: bool, duration_s: float | None = None) -> dict:
    event = {"event": "check_finished", "attempt": 0, "name": name, "passed": passed}
    if duration_s is not None:
        event["duration_s"] = duration_s
    return event


# ---------------------------------------------------------------------------
# check_history — the pure aggregation.
# ---------------------------------------------------------------------------


class TestCheckHistoryAggregation:
    def test_absent_runs_dir_is_empty(self, tmp_path: Path) -> None:
        assert check_history(tmp_path / "nope") == []

    def test_empty_runs_dir_is_empty(self, tmp_path: Path) -> None:
        (tmp_path / "runs").mkdir()
        assert check_history(tmp_path / "runs") == []

    def test_single_always_passing_check(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _write_log(
            runs_dir,
            "20260101T000000-task-a-aaaaaa",
            [_check_finished("test", True, 1.0), _check_finished("test", True, 2.0)],
        )

        [h] = check_history(runs_dir)

        assert h == CheckHistory(
            name="test", runs=2, passes=2, pass_rate=1.0, mean_duration_s=1.5, flake_score=0.0
        )

    def test_always_failing_check_has_zero_flake_score(self, tmp_path: Path) -> None:
        # Consistently broken is NOT flaky — the outcome never flips.
        runs_dir = tmp_path / "runs"
        _write_log(
            runs_dir,
            "20260101T000000-task-a-aaaaaa",
            [_check_finished("lint", False), _check_finished("lint", False), _check_finished("lint", False)],
        )

        [h] = check_history(runs_dir)

        assert h.pass_rate == 0.0
        assert h.flake_score == 0.0

    def test_alternating_outcomes_maximize_flake_score(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _write_log(
            runs_dir,
            "20260101T000000-task-a-aaaaaa",
            [
                _check_finished("test", True),
                _check_finished("test", False),
                _check_finished("test", True),
                _check_finished("test", False),
            ],
        )

        [h] = check_history(runs_dir)

        assert h.runs == 4
        assert h.pass_rate == 0.5
        assert h.flake_score == 1.0  # every consecutive pair flips

    def test_partial_flakiness_is_a_fraction(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _write_log(
            runs_dir,
            "20260101T000000-task-a-aaaaaa",
            [
                _check_finished("test", True),
                _check_finished("test", True),
                _check_finished("test", False),
                _check_finished("test", True),
            ],
        )

        [h] = check_history(runs_dir)

        # 3 gaps, 2 flips (T->T no, T->F yes, F->T yes) = 2/3.
        assert h.flake_score == 2 / 3

    def test_single_run_has_zero_flake_score(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _write_log(runs_dir, "20260101T000000-task-a-aaaaaa", [_check_finished("test", False)])

        [h] = check_history(runs_dir)

        assert h.runs == 1
        assert h.flake_score == 0.0

    def test_events_are_ordered_across_files_by_filename(self, tmp_path: Path) -> None:
        # Two runs, one event each, filenames are time-ordered — chronological
        # order across files must match filename order, not write order.
        runs_dir = tmp_path / "runs"
        _write_log(runs_dir, "20260101T000002-task-b-bbbbbb", [_check_finished("test", False)])
        _write_log(runs_dir, "20260101T000001-task-a-aaaaaa", [_check_finished("test", True)])

        [h] = check_history(runs_dir)

        # Chronological sequence is [True, False] -> one flip out of one gap.
        assert h.flake_score == 1.0

    def test_multiple_checks_aggregated_separately_and_sorted(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _write_log(
            runs_dir,
            "20260101T000000-task-a-aaaaaa",
            [_check_finished("zeta", True), _check_finished("alpha", False)],
        )

        history = check_history(runs_dir)

        assert [h.name for h in history] == ["alpha", "zeta"]

    def test_missing_duration_is_excluded_from_the_mean_not_treated_as_zero(
        self, tmp_path: Path
    ) -> None:
        # An event from an OLDER run log (pre-T9) has no duration_s at all.
        runs_dir = tmp_path / "runs"
        _write_log(
            runs_dir,
            "20260101T000000-task-a-aaaaaa",
            [_check_finished("test", True, 4.0), _check_finished("test", True, None)],
        )

        [h] = check_history(runs_dir)

        assert h.runs == 2  # still counted for pass-rate/flake-score
        assert h.mean_duration_s == 4.0  # the ONE event that reported a duration

    def test_no_duration_anywhere_yields_zero_mean(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _write_log(runs_dir, "20260101T000000-task-a-aaaaaa", [_check_finished("test", True)])

        [h] = check_history(runs_dir)

        assert h.mean_duration_s == 0.0

    def test_non_check_finished_events_are_ignored(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        _write_log(
            runs_dir,
            "20260101T000000-task-a-aaaaaa",
            [
                {"event": "mandate_started", "blueprint": "chore"},
                _check_finished("test", True),
                {"event": "act_finished", "ok": True},
            ],
        )

        [h] = check_history(runs_dir)

        assert h.runs == 1

    def test_malformed_lines_are_skipped_not_fatal(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        path = runs_dir / "20260101T000000-task-a-aaaaaa.jsonl"
        path.write_text(
            "not json at all\n"
            + json.dumps(_check_finished("test", True))
            + "\n\n"  # blank line
        )

        [h] = check_history(runs_dir)

        assert h.runs == 1

    def test_unreadable_file_is_skipped(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        garbage_dir = runs_dir / "not-a-file.jsonl"
        garbage_dir.mkdir()  # a directory named *.jsonl -> read_text() raises

        assert check_history(runs_dir) == []


# ---------------------------------------------------------------------------
# CLI — `alc checks history [--json]`.
# ---------------------------------------------------------------------------


def _ns(**overrides) -> argparse.Namespace:
    defaults = {"checks_action": "history", "json": False}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestChecksHistoryCli:
    def test_dispatches_from_cmd_checks(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)
        assert cmd_checks(_ns()) == 0
        out = capsys.readouterr().out
        assert "No check history yet" in out

    def test_never_writes_anything(self, operator_layer: Path, monkeypatch) -> None:
        monkeypatch.chdir(operator_layer.parent)
        before = sorted(p.relative_to(operator_layer.parent) for p in operator_layer.rglob("*"))
        assert cmd_checks(_ns()) == 0
        after = sorted(p.relative_to(operator_layer.parent) for p in operator_layer.rglob("*"))
        assert before == after

    def test_prints_pass_rate_duration_and_flake_score(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        runs_dir = operator_layer.parent / ".alc" / "runs"
        _write_log(
            runs_dir,
            "20260101T000000-task-a-aaaaaa",
            [_check_finished("test", True, 1.0), _check_finished("test", False, 3.0)],
        )
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_checks(_ns()) == 0

        out = capsys.readouterr().out
        assert "test" in out
        assert "pass_rate=50%" in out
        assert "flake_score=1.00" in out

    def test_json_output_matches_check_history(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        runs_dir = operator_layer.parent / ".alc" / "runs"
        _write_log(
            runs_dir,
            "20260101T000000-task-a-aaaaaa",
            [_check_finished("test", True, 1.0)],
        )
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_checks(_ns(json=True)) == 0

        data = json.loads(capsys.readouterr().out)
        assert data == [
            {
                "name": "test",
                "runs": 1,
                "passes": 1,
                "pass_rate": 1.0,
                "mean_duration_s": 1.0,
                "flake_score": 0.0,
            }
        ]
