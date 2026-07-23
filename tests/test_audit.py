# test_audit.py — Hermetic tests for `alc audit`: parse_since / audit_window
# (src/alc/audit.py) and the `cmd_audit` CLI shell over them.
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import pytest

from alc.audit import audit_window, parse_since
from alc.cli import cmd_audit


def _write_report(
    done_dir: Path,
    stem: str,
    *,
    success: bool = True,
    span: int = 1,
    passes: int = 1,
    streak: int = 1,
    touch: int = 0,
    changed_files: list[str] | None = None,
    usage: dict | None = None,
    age_s: float = 0.0,
) -> Path:
    """Write one archived `<stem>.report.json` FlowReport and backdate its mtime."""
    done_dir.mkdir(parents=True, exist_ok=True)
    stage = {
        "blueprint": "chore",
        "engine": "mock",
        "success": success,
        "attempts": [],
        "scorecard": {"span": span, "passes": passes, "streak": streak, "touch": touch},
        "output_text": "",
        "changed_files": changed_files or [],
        "usage": usage,
    }
    report = {
        "flow": "ship",
        "engine": "mock",
        "success": success,
        "stages": [stage],
        "scorecard": {"span": span, "passes": passes, "streak": streak, "touch": touch},
    }
    path = done_dir / f"{stem}.report.json"
    path.write_text(json.dumps(report))
    if age_s:
        mtime = time.time() - age_s
        os.utime(path, (mtime, mtime))
    return path


# ---------------------------------------------------------------------------
# parse_since
# ---------------------------------------------------------------------------


class TestParseSince:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [("7d", 7 * 86400), ("24h", 24 * 3600), ("30m", 30 * 60), ("1d", 86400)],
    )
    def test_parses_each_unit(self, value: str, expected: int) -> None:
        assert parse_since(value) == expected

    @pytest.mark.parametrize("value", ["7", "7x", "d7", "", "7d ago", "-7d"])
    def test_unparseable_value_raises_clear_error(self, value: str) -> None:
        with pytest.raises(ValueError, match="invalid --since value"):
            parse_since(value)


# ---------------------------------------------------------------------------
# audit_window
# ---------------------------------------------------------------------------


class TestAuditWindowEmpty:
    def test_missing_done_dir_is_an_all_zero_window(self, tmp_path: Path) -> None:
        window = audit_window(tmp_path / "done", since_epoch=0.0)
        assert window.tasks_total == 0
        assert window.tasks_ok == 0
        assert window.tasks_failed == 0
        assert window.span_avg == 0.0
        assert window.cost_usd_total == 0.0


class TestAuditWindowAggregation:
    def test_counts_and_totals_across_reports(self, tmp_path: Path) -> None:
        done_dir = tmp_path / "done"
        _write_report(done_dir, "a", success=True, span=2, passes=1, streak=1, touch=0)
        _write_report(done_dir, "b", success=False, span=1, passes=3, streak=0, touch=1)

        window = audit_window(done_dir, since_epoch=0.0)

        assert window.tasks_total == 2
        assert window.tasks_ok == 1
        assert window.tasks_failed == 1
        assert window.span_total == 3
        assert window.span_avg == pytest.approx(1.5)
        assert window.passes_total == 4
        assert window.passes_avg == pytest.approx(2.0)
        assert window.streak_total == 1
        assert window.touch_total == 1

    def test_changed_files_summed_across_stages(self, tmp_path: Path) -> None:
        done_dir = tmp_path / "done"
        _write_report(done_dir, "a", changed_files=["x.py", "y.py"])
        _write_report(done_dir, "b", changed_files=["z.py"])

        window = audit_window(done_dir, since_epoch=0.0)
        assert window.changed_files_total == 3

    def test_usage_accumulated_from_usage_field(self, tmp_path: Path) -> None:
        done_dir = tmp_path / "done"
        _write_report(
            done_dir,
            "a",
            usage={"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.02},
        )
        _write_report(
            done_dir,
            "b",
            usage={"input_tokens": 10, "output_tokens": None, "cost_usd": 0.01},
        )
        _write_report(done_dir, "c", usage=None)  # no usage reported -> contributes nothing

        window = audit_window(done_dir, since_epoch=0.0)
        assert window.input_tokens_total == 110
        assert window.output_tokens_total == 50
        assert window.cost_usd_total == pytest.approx(0.03)

    def test_reports_older_than_since_are_excluded(self, tmp_path: Path) -> None:
        done_dir = tmp_path / "done"
        _write_report(done_dir, "old", span=5, age_s=10 * 86400)
        _write_report(done_dir, "recent", span=7, age_s=0)

        window = audit_window(done_dir, since_epoch=time.time() - 7 * 86400)

        assert window.tasks_total == 1
        assert window.span_total == 7

    def test_unreadable_report_is_skipped_not_fatal(self, tmp_path: Path) -> None:
        done_dir = tmp_path / "done"
        done_dir.mkdir(parents=True)
        (done_dir / "broken.report.json").write_text("not json")
        _write_report(done_dir, "ok", span=4)

        window = audit_window(done_dir, since_epoch=0.0)
        assert window.tasks_total == 1
        assert window.span_total == 4


# ---------------------------------------------------------------------------
# cmd_audit — the CLI shell
# ---------------------------------------------------------------------------


def _ns(**overrides) -> argparse.Namespace:
    defaults = {"since": "7d", "json": False}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestCmdAuditInvalidSince:
    def test_unparseable_since_is_a_clear_error_exit_1(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_audit(_ns(since="nonsense")) == 1
        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert "invalid --since value" in err


class TestCmdAuditHuman:
    def test_no_archive_prints_zeroed_summary(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_audit(_ns()) == 0
        out = capsys.readouterr().out
        assert "Tasks:            0 total, 0 ok, 0 failed" in out

    def test_reports_within_window_are_counted(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        done_dir = operator_layer / "queue" / "done"
        _write_report(done_dir, "a", success=True, span=3)
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_audit(_ns()) == 0
        out = capsys.readouterr().out
        assert "Tasks:            1 total, 1 ok, 0 failed" in out


class TestCmdAuditJson:
    def test_json_output_is_machine_readable(
        self, operator_layer: Path, monkeypatch, capsys
    ) -> None:
        done_dir = operator_layer / "queue" / "done"
        _write_report(done_dir, "a", success=True, span=3)
        monkeypatch.chdir(operator_layer.parent)

        assert cmd_audit(_ns(json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["tasks_total"] == 1
        assert data["tasks_ok"] == 1
        assert data["span_total"] == 3
