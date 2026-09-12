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


class TestVerifierInnerTimeout:
    # A check can fail because its OWN test runner (vitest/jest/mocha) killed a
    # single test for exceeding that runner's per-test deadline under load — the
    # process exits non-zero WITHIN ALC's budget, so it looks identical to an
    # assertion failure. These assert we surface it as timed_out instead.
    def test_vitest_inner_timeout_is_marked(self, tmp_path: Path) -> None:
        [result] = Verifier(timeout_s=30).run(
            [Check(name="t", shell="echo 'Test timed out in 5000ms'; exit 1")], tmp_path
        )
        assert result.passed is False  # a timed-out check is still not green
        assert result.timed_out is True
        assert "test-runner timeout" in result.output  # the honest annotation
        assert "Test timed out in 5000ms" in result.output  # original tail kept

    def test_jest_async_callback_timeout_is_marked(self, tmp_path: Path) -> None:
        [result] = Verifier(timeout_s=30).run(
            [
                Check(
                    name="t",
                    shell="echo 'Timeout - Async callback was not invoked within the 5000 ms timeout'; exit 1",
                )
            ],
            tmp_path,
        )
        assert result.timed_out is True

    def test_jest_exceeded_timeout_is_marked(self, tmp_path: Path) -> None:
        [result] = Verifier(timeout_s=30).run(
            [Check(name="t", shell="echo 'Exceeded timeout of 2000ms for a hook'; exit 1")],
            tmp_path,
        )
        assert result.timed_out is True

    def test_mocha_timeout_exceeded_is_marked(self, tmp_path: Path) -> None:
        [result] = Verifier(timeout_s=30).run(
            [Check(name="t", shell="echo 'Error: timeout of 2000ms exceeded'; exit 1")],
            tmp_path,
        )
        assert result.timed_out is True

    def test_plain_assertion_failure_is_not_flagged(self, tmp_path: Path) -> None:
        [result] = Verifier(timeout_s=30).run(
            [Check(name="t", shell="echo 'expected 1 to equal 2'; exit 1")], tmp_path
        )
        assert result.passed is False
        assert result.timed_out is False  # a real failure stays a plain failure

    def test_bare_word_timeout_in_prose_is_not_flagged(self, tmp_path: Path) -> None:
        # The generic word "timeout" appears in too much unrelated output to be a
        # safe signal — only the specific runner signatures count.
        [result] = Verifier(timeout_s=30).run(
            [Check(name="t", shell="echo 'the timeout option is documented above'; exit 1")],
            tmp_path,
        )
        assert result.passed is False
        assert result.timed_out is False

    def test_passing_check_with_timeout_wording_is_untouched(self, tmp_path: Path) -> None:
        # A PASSING check is never re-classified, even if its output happens to
        # contain a signature — the detector only runs on a non-zero exit.
        [result] = Verifier(timeout_s=30).run(
            [Check(name="t", shell="echo 'Test timed out in 5000ms'; exit 0")], tmp_path
        )
        assert result.passed is True
        assert result.timed_out is False


class TestVerifierOutcome:
    def test_passing_check_reports_duration_and_exit_code(self, tmp_path: Path) -> None:
        [result] = Verifier(timeout_s=30).run([Check(name="ok", command=["true"])], tmp_path)
        assert result.exit_code == 0
        assert result.duration_s >= 0.0

    def test_failing_check_reports_nonzero_exit_code(self, tmp_path: Path) -> None:
        [result] = Verifier(timeout_s=30).run(
            [Check(name="boom", shell="exit 7")], tmp_path
        )
        assert result.exit_code == 7
        assert result.duration_s >= 0.0

    def test_check_that_cannot_start_has_no_exit_code(self, tmp_path: Path) -> None:
        [result] = Verifier(timeout_s=30).run(
            [Check(name="missing", command=["no-such-binary-xyz"])], tmp_path
        )
        assert result.passed is False
        assert result.exit_code is None

    def test_timed_out_check_still_reports_a_duration(self, tmp_path: Path) -> None:
        [result] = Verifier(timeout_s=1).run([Check(name="hang", shell="sleep 30")], tmp_path)
        assert result.timed_out is True
        assert result.duration_s >= 1.0


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


class TestVerifierEnv:
    """Finding 50: the run's env (ALC_BASE_URL on a needs_service run) must
    reach check subprocesses — the engine and `capture:` always saw it, the
    Verifier never did, so the builder's own e2e-smoke check could not pass."""

    def test_env_reaches_check_subprocess(self, tmp_path: Path) -> None:
        [result] = Verifier(env={"ALC_BASE_URL": "http://127.0.0.1:9999"}).run(
            [Check(name="see", shell='test "$ALC_BASE_URL" = "http://127.0.0.1:9999"')],
            tmp_path,
        )
        assert result.passed is True

    def test_env_merges_over_environ_not_replaces(self, tmp_path: Path) -> None:
        # PATH must survive the merge, or no check could even start.
        [result] = Verifier(env={"ALC_X": "1"}).run(
            [Check(name="both", shell='test -n "$PATH" && test "$ALC_X" = 1')],
            tmp_path,
        )
        assert result.passed is True

    def test_no_env_inherits_environ_unchanged(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("ALC_TEST_INHERIT", "yes")
        [result] = Verifier().run(
            [Check(name="inh", shell='test "$ALC_TEST_INHERIT" = yes')], tmp_path
        )
        assert result.passed is True

    def test_metric_check_sees_env(self, tmp_path: Path) -> None:
        # The metric path spawns its own subprocess — same env contract.
        [result] = Verifier(env={"ALC_N": "42"}).run(
            [Check(name="m", metric='echo "$ALC_N"', direction="lower_is_better")],
            tmp_path,
        )
        assert result.passed is True
        assert "42" in result.output
