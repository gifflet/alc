# test_assurance.py — THE KEY TEST: proves the Assurance Loop re-invokes the engine
# when checks fail and repairs on the next attempt.
# All tests are hermetic (no real model, no network).
from __future__ import annotations

from pathlib import Path


from alc.assurance import AssuranceLoop
from alc.engine import Capabilities, EngineRequest, EngineResult
from alc.engines.mock import MockEngine
from alc.models import Check
from alc.verifier import CheckResult, Verifier


class _FailingEngine:
    """An engine whose turn always fails to run (e.g. bad flag / missing binary)."""

    name = "failing"

    def capabilities(self) -> Capabilities:
        return Capabilities()

    def health_check(self) -> bool:
        return True

    def run(self, request: EngineRequest) -> EngineResult:
        return EngineResult(ok=False, output_text="boom: error: unknown option")


def _make_request(workdir: Path) -> EngineRequest:
    return EngineRequest(
        directive="# Single-Mandate chore\nDo the task.",
        workdir=workdir,
    )


def _marker_checks() -> list[Check]:
    """A single check that passes when done.txt exists in the workdir."""
    return [Check(name="marker", command=["test", "-f", "done.txt"])]


class TestAssuranceLoopEngineFailure:
    """A failing engine short-circuits: fail fast, surface the error, no wasted repairs."""

    def test_short_circuits_and_surfaces_error(self, tmp_path: Path) -> None:
        # The check would PASS (file already present), but the engine failed to run —
        # the loop must still fail and not mask the engine error.
        (tmp_path / "done.txt").write_text("ok")
        loop = AssuranceLoop(engine=_FailingEngine(), verifier=Verifier(), max_repairs=3)
        report = loop.run(_make_request(tmp_path), checks=_marker_checks())

        assert report.success is False
        assert len(report.attempts) == 1  # did NOT waste the repair budget
        assert report.attempts[0].engine_ok is False
        assert "unknown option" in report.output_text


class TestAssuranceLoopRepair:
    """Attempt 0 fails (no file), attempt 1 passes (file created)."""

    def test_repair_on_failure(self, tmp_path: Path) -> None:
        behaviors = [
            lambda wd: None,                                          # attempt 0: no-op
            lambda wd: (wd / "done.txt").write_text("ok"),            # attempt 1: create file
        ]
        engine = MockEngine(behaviors=behaviors)
        verifier = Verifier()
        loop = AssuranceLoop(engine=engine, verifier=verifier, max_repairs=3)

        request = _make_request(tmp_path)
        report = loop.run(request=request, checks=_marker_checks())

        assert report.success is True
        assert len(report.attempts) == 2
        # Attempt 0 should have failed the check.
        assert "marker" in report.attempts[0].failed_checks
        # Attempt 1 should have no failed checks.
        assert report.attempts[1].failed_checks == []
        # streak == 0 because a repair was needed.
        assert report.scorecard.streak == 0
        # passes == 2 (two engine turns).
        assert report.scorecard.passes == 2


class TestAssuranceLoopOneShot:
    """Behavior[0] already creates the file — one-shot success (streak == 1)."""

    def test_one_shot_success(self, tmp_path: Path) -> None:
        behaviors = [
            lambda wd: (wd / "done.txt").write_text("ok"),  # attempt 0: immediate success
        ]
        engine = MockEngine(behaviors=behaviors)
        verifier = Verifier()
        loop = AssuranceLoop(engine=engine, verifier=verifier, max_repairs=3)

        request = _make_request(tmp_path)
        report = loop.run(request=request, checks=_marker_checks())

        assert report.success is True
        assert len(report.attempts) == 1
        assert report.attempts[0].failed_checks == []
        # streak == 1 because zero repairs needed.
        assert report.scorecard.streak == 1
        # passes == 1 (one engine turn).
        assert report.scorecard.passes == 1


# ---------------------------------------------------------------------------
# env_refresh seam — reinstall the ecosystem AFTER Act, BEFORE Verify, when a
# run bumped a dependency manifest (the deps-bump false green fix).
# ---------------------------------------------------------------------------


class _RecordingEngine:
    """An engine that records the order of its turns and every directive it saw."""

    name = "rec"

    def __init__(self, log: list[str], directives: list[str]) -> None:
        self._log = log
        self._directives = directives

    def capabilities(self) -> Capabilities:
        return Capabilities()

    def health_check(self) -> bool:
        return True

    def run(self, request: EngineRequest) -> EngineResult:
        self._log.append("act")
        self._directives.append(request.directive)
        return EngineResult(ok=True, output_text="[rec] done")


class _RecordingVerifier:
    """A Verifier stand-in that records each call and returns canned results."""

    def __init__(self, log: list[str], results: list[CheckResult]) -> None:
        self._log = log
        self._results = results
        self.calls = 0

    def run(self, checks, workdir, on_check_start=None, on_check_done=None):
        self._log.append("verify")
        self.calls += 1
        return list(self._results)


class TestAssuranceLoopEnvRefresh:
    def test_refresh_runs_after_act_before_verify(self, tmp_path: Path) -> None:
        log: list[str] = []
        directives: list[str] = []

        def _refresh() -> CheckResult | None:
            log.append("refresh")
            return None

        loop = AssuranceLoop(
            engine=_RecordingEngine(log, directives),
            verifier=_RecordingVerifier(log, [CheckResult("smoke", True, "")]),
            max_repairs=0,
            env_refresh=_refresh,
        )
        report = loop.run(_make_request(tmp_path), checks=[Check(name="smoke", command=["true"])])

        assert report.success is True
        # The refresh sits strictly between the Act turn and the Verify pass.
        assert log == ["act", "refresh", "verify"]

    def test_refresh_failure_skips_verify_and_feeds_repair(self, tmp_path: Path) -> None:
        log: list[str] = []
        directives: list[str] = []

        class _AlwaysFailingRefresh:
            def __init__(self) -> None:
                self.calls = 0

            def __call__(self) -> CheckResult | None:
                self.calls += 1
                log.append("refresh")
                return CheckResult(
                    name="env-refresh",
                    passed=False,
                    output="npm ERR! peer dep conflict during install",
                    exit_code=1,
                )

        refresh = _AlwaysFailingRefresh()
        verifier = _RecordingVerifier(log, [CheckResult("smoke", True, "")])
        loop = AssuranceLoop(
            engine=_RecordingEngine(log, directives),
            verifier=verifier,
            max_repairs=1,
            env_refresh=refresh,
        )
        report = loop.run(_make_request(tmp_path), checks=[Check(name="smoke", command=["true"])])

        # A broken refresh is a red attempt: the run must fail, never a false green.
        assert report.success is False
        # env-refresh is recorded as the failing check on every attempt.
        assert "env-refresh" in report.attempts[0].failed_checks
        assert "env-refresh" in report.attempts[1].failed_checks
        # The Verifier was SKIPPED on both failing attempts — its only call is the
        # final post-budget re-verify (span accounting), not the two attempts. So a
        # would-be-passing check never masqueraded as passed inside a red attempt.
        assert verifier.calls == 1
        # Two attempts -> the refresh was re-invoked on the repair attempt.
        assert refresh.calls == 2
        # The repair addendum carried the install's stderr into the next turn.
        assert "peer dep conflict" in directives[1]

    def test_env_refresh_none_is_byte_identical(self, tmp_path: Path) -> None:
        # With no env_refresh bound the loop behaves exactly as before: a real
        # Verifier runs the checks directly on every attempt.
        behaviors = [lambda wd: (wd / "done.txt").write_text("ok")]
        loop = AssuranceLoop(
            engine=MockEngine(behaviors=behaviors),
            verifier=Verifier(),
            max_repairs=3,
        )
        report = loop.run(_make_request(tmp_path), checks=_marker_checks())
        assert report.success is True
        assert report.scorecard.streak == 1


class TestAssuranceLoopBudgetExhausted:
    """Checks never pass — loop exhausts repair budget and returns success=False."""

    def test_budget_exhausted(self, tmp_path: Path) -> None:
        engine = MockEngine(behaviors=[lambda wd: None])  # always no-op
        verifier = Verifier()
        loop = AssuranceLoop(engine=engine, verifier=verifier, max_repairs=2)

        request = _make_request(tmp_path)
        report = loop.run(request=request, checks=_marker_checks())

        assert report.success is False
        assert len(report.attempts) == 3  # initial + 2 repairs
        assert report.scorecard.streak == 0
