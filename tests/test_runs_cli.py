# test_runs_cli.py — Hermetic tests for `alc runs list|show|tail`: the CLI shell
# over the core readers in src/alc/runs.py. Uses the conftest `operator_layer`
# fixture (default runs_dir: .alc/runs).
from __future__ import annotations

import argparse
import json
from pathlib import Path

from alc.cli import cmd_runs


def _write_run(operator_layer: Path, stem: str, events: list[str]) -> Path:
    runs_dir = operator_layer / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    body = "".join(f'{{"event": "{e}", "n": {i}}}\n' for i, e in enumerate(events))
    path = runs_dir / f"{stem}.jsonl"
    path.write_text(body)
    return path


def _ns(**overrides) -> argparse.Namespace:
    defaults = {
        "runs_action": "list",
        "limit": 50,
        "offset": 0,
        "json": False,
        "stem": None,
        "lines": 20,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


class TestRunsListHuman:
    def test_no_runs_prints_message(self, operator_layer: Path, monkeypatch, capsys) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_runs(_ns(runs_action="list")) == 0
        assert "No runs." in capsys.readouterr().out

    def test_lists_run_stems_with_kind_and_status(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        _write_run(
            operator_layer,
            "20260101T000000-flow-done-aaaaaa",
            ["flow_started", "flow_finished"],
        )
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_runs(_ns(runs_action="list")) == 0
        out = capsys.readouterr().out
        assert "20260101T000000-flow-done-aaaaaa" in out
        assert "(flow, finished)" in out
        assert "Showing 1 of 1 run(s)." in out


class TestRunsListJson:
    def test_json_output_matches_core_reader(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        _write_run(operator_layer, "20260101T000000-flow-done-aaaaaa", ["flow_started"])
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_runs(_ns(runs_action="list", json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["total"] == 1
        assert data["runs"][0]["stem"] == "20260101T000000-flow-done-aaaaaa"


class TestRunsListPagination:
    def test_limit_and_offset_are_forwarded(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        import time

        for i in range(3):
            _write_run(operator_layer, f"2026010{i}T000000-run-x-{i:06d}", ["mandate_finished"])
            time.sleep(0.01)
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_runs(_ns(runs_action="list", limit=1, offset=1, json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["total"] == 3
        assert len(data["runs"]) == 1


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


class TestRunsShow:
    def test_missing_run_is_a_clear_error(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_runs(_ns(runs_action="show", stem="ghost")) == 1
        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert "ghost" in err

    def test_prints_every_event_as_json_lines(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        _write_run(
            operator_layer, "20260101T000000-run-x-aaaaaa", ["mandate_started", "mandate_finished"]
        )
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_runs(_ns(runs_action="show", stem="20260101T000000-run-x-aaaaaa")) == 0
        lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
        assert len(lines) == 2
        assert json.loads(lines[0])["event"] == "mandate_started"
        assert json.loads(lines[1])["event"] == "mandate_finished"

    def test_json_flag_wraps_events_and_next_offset(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        _write_run(operator_layer, "20260101T000000-run-x-aaaaaa", ["a", "b"])
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_runs(_ns(runs_action="show", stem="20260101T000000-run-x-aaaaaa", json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["next_offset"] == 2
        assert [e["event"] for e in data["events"]] == ["a", "b"]


# ---------------------------------------------------------------------------
# tail
# ---------------------------------------------------------------------------


class TestRunsTail:
    def test_missing_run_is_a_clear_error(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_runs(_ns(runs_action="tail", stem="ghost")) == 1
        assert "[ERROR]" in capsys.readouterr().err

    def test_prints_only_the_last_n_events(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        events = [f"event_{i}" for i in range(5)]
        _write_run(operator_layer, "20260101T000000-run-x-aaaaaa", events)
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_runs(_ns(runs_action="tail", stem="20260101T000000-run-x-aaaaaa", lines=2)) == 0
        lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
        assert [json.loads(ln)["event"] for ln in lines] == ["event_3", "event_4"]

    def test_default_n_is_20(self, operator_layer: Path, monkeypatch, capsys) -> None:
        events = [f"event_{i}" for i in range(25)]
        _write_run(operator_layer, "20260101T000000-run-x-aaaaaa", events)
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_runs(_ns(runs_action="tail", stem="20260101T000000-run-x-aaaaaa")) == 0
        lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
        assert len(lines) == 20
        assert json.loads(lines[0])["event"] == "event_5"
