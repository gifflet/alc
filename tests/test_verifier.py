# test_verifier.py — check timeout (kills the whole process group) + real-time callbacks.
from __future__ import annotations

import time
from pathlib import Path

from alc.models import Check
from alc.verifier import CheckResult, Verifier


class TestVerifierTimeout:
    def test_hanging_check_times_out_fast_and_is_marked(self, tmp_path: Path) -> None:
        start = time.monotonic()
        [result] = Verifier(timeout_s=1).run([Check(name="hang", shell="sleep 30")], tmp_path)
        assert result.passed is False
        assert result.timed_out is True
        assert "timed out after 1s" in result.output
        assert (time.monotonic() - start) < 10  # killed at ~1s, not 30s

    def test_backgrounded_child_is_killed_with_the_group(self, tmp_path: Path) -> None:
        # A check that backgrounds a child (mirrors `pnpm` -> `node --test`) then waits.
        # If only the parent were killed the orphan would write the marker at 2s; killing
        # the whole GROUP at the 1s timeout means the marker is never written.
        marker = tmp_path / "child-ran.txt"
        shell = f"(sleep 2; echo x > {marker}) & sleep 30"
        [result] = Verifier(timeout_s=1).run([Check(name="hang", shell=shell)], tmp_path)
        assert result.timed_out is True
        time.sleep(2.5)  # long enough for the child to have written, had it survived
        assert not marker.exists()

    def test_passing_check_is_not_timed_out(self, tmp_path: Path) -> None:
        [result] = Verifier(timeout_s=30).run([Check(name="ok", command=["true"])], tmp_path)
        assert result.passed is True
        assert result.timed_out is False

    def test_failing_check_reports_output_without_timeout(self, tmp_path: Path) -> None:
        [result] = Verifier(timeout_s=30).run(
            [Check(name="boom", shell="echo nope 1>&2; exit 1")], tmp_path
        )
        assert result.passed is False
        assert result.timed_out is False
        assert "nope" in result.output

    def test_no_timeout_runs_to_completion(self, tmp_path: Path) -> None:
        # Default timeout_s=None => never times out (backward compatible).
        [result] = Verifier().run([Check(name="ok", command=["true"])], tmp_path)
        assert result.passed is True
        assert result.timed_out is False


class TestVerifierCallbacks:
    def test_callbacks_fire_per_check_in_order(self, tmp_path: Path) -> None:
        started: list[str] = []
        done: list[CheckResult] = []
        Verifier(timeout_s=30).run(
            [Check(name="a", command=["true"]), Check(name="b", command=["false"])],
            tmp_path,
            on_check_start=started.append,
            on_check_done=done.append,
        )
        assert started == ["a", "b"]  # each surfaced BEFORE it runs
        assert [(r.name, r.passed) for r in done] == [("a", True), ("b", False)]
