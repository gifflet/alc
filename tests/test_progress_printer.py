# test_progress_printer.py — the shared, engine-agnostic live-progress noise control.
from __future__ import annotations

import json
from pathlib import Path

from alc.engine import ProgressPrinter
from alc.events import bind_run_log


class TestProgressPrinter:
    def test_collapses_consecutive_repeats(self, capsys) -> None:
        p = ProgressPrinter()
        p.emit("same")
        p.emit("same")
        p.emit("same")
        assert capsys.readouterr().err.count("same") == 1

    def test_non_consecutive_repeats_both_print(self, capsys) -> None:
        # Dedup is consecutive-only — A, B, A prints A twice.
        p = ProgressPrinter()
        p.emit("A")
        p.emit("B")
        p.emit("A")
        assert capsys.readouterr().err.count("A") == 2

    def test_truncates_to_max_width(self, capsys) -> None:
        p = ProgressPrinter(max_width=5)
        p.emit("abcdefghij")
        err = capsys.readouterr().err
        assert "abcde" in err
        assert "abcdef" not in err

    def test_caps_total_and_summarizes_on_close(self, capsys) -> None:
        p = ProgressPrinter(max_lines=2)
        for line in ("one", "two", "three", "four"):
            p.emit(line)
        p.close()
        err = capsys.readouterr().err
        assert "one" in err and "two" in err
        assert "three" not in err and "four" not in err
        assert "2 more line(s) suppressed" in err

    def test_skips_blank_lines(self, capsys) -> None:
        p = ProgressPrinter()
        p.emit("   ")
        p.emit("")
        assert capsys.readouterr().err == ""

    def test_close_without_suppression_is_silent(self, capsys) -> None:
        p = ProgressPrinter()
        p.emit("x")
        capsys.readouterr()  # clear
        p.close()
        assert "suppressed" not in capsys.readouterr().err

    def test_close_is_idempotent(self, capsys) -> None:
        p = ProgressPrinter(max_lines=1)
        p.emit("a")
        p.emit("b")  # suppressed
        p.close()
        assert "suppressed" in capsys.readouterr().err
        p.close()  # a second close must not re-emit the summary
        assert "suppressed" not in capsys.readouterr().err


class TestProgressPrinterRunLog:
    """The `event` param persists activity to the bound run log — engine-agnostic
    observability that ANY adapter opts into by naming its activity printer."""

    def _events(self, log: Path) -> list[dict]:
        return [json.loads(ln) for ln in log.read_text().splitlines() if ln.strip()]

    def test_event_persists_each_printed_note(self, tmp_path: Path) -> None:
        log = tmp_path / "run.jsonl"
        with bind_run_log(log):
            p = ProgressPrinter(event="engine_activity")
            p.emit("Bash: grep -rn STEPS .")
            p.emit("Read: /app/foo.js")
        assert [(e["event"], e["note"]) for e in self._events(log)] == [
            ("engine_activity", "Bash: grep -rn STEPS ."),
            ("engine_activity", "Read: /app/foo.js"),
        ]

    def test_persists_the_full_untruncated_note(self, tmp_path: Path) -> None:
        # stderr truncates to max_width; the run log keeps the FULL note.
        log = tmp_path / "run.jsonl"
        with bind_run_log(log):
            ProgressPrinter(event="engine_activity", max_width=5).emit("abcdefghij")
        assert self._events(log)[0]["note"] == "abcdefghij"

    def test_consecutive_repeat_dedups_the_run_log_too(self, tmp_path: Path) -> None:
        log = tmp_path / "run.jsonl"
        with bind_run_log(log):
            p = ProgressPrinter(event="engine_activity")
            p.emit("same")
            p.emit("same")
        assert len(self._events(log)) == 1

    def test_no_event_writes_nothing(self, tmp_path: Path) -> None:
        log = tmp_path / "run.jsonl"
        with bind_run_log(log):
            ProgressPrinter().emit("Bash: x")  # default event=None -> stderr only
        assert not log.exists() or log.read_text().strip() == ""

    def test_no_run_log_bound_is_a_noop(self, capsys) -> None:
        # event set but nothing bound -> prints to stderr, never raises.
        ProgressPrinter(event="engine_activity").emit("Bash: x")
        assert "Bash: x" in capsys.readouterr().err
