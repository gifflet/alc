# test_progress_printer.py — the shared, engine-agnostic live-progress noise control.
from __future__ import annotations

from alc.engine import ProgressPrinter


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
