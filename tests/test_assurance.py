# test_assurance.py — THE KEY TEST: proves the Assurance Loop re-invokes the engine
# when checks fail and repairs on the next attempt.
# All tests are hermetic (no real model, no network).
from __future__ import annotations

from pathlib import Path

import pytest

from alc.assurance import AssuranceLoop
from alc.engine import Capabilities, EngineRequest, EngineResult
from alc.engines.mock import MockEngine
from alc.models import Check
from alc.verifier import Verifier


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
