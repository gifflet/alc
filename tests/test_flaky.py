# test_flaky.py — Hermetic tests for roadmap-phase-3.md T11: `flaky: N` per
# check (the Verifier reruns a failing check before an engine repair turn is
# spent) plus declarative quarantine (`manifest.quarantined_checks`: a check
# still runs but can never fail the run, and the Policy Gate warns forever).
#
# (a) Check.flaky front-matter + validation.
# (b) Verifier: the flaky rerun loop itself.
# (c) AssuranceLoop: a quarantined check's failure is recorded but never blocks
#     success or spends a repair turn.
# (d) runner.py wiring: manifest.quarantined_checks reaches the loop.
# (e) Policy Gate: permanent warn for every listed quarantined check.
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from alc.assurance import AssuranceLoop
from alc.engine import Capabilities, EngineRequest, EngineResult
from alc.engines.mock import MockEngine
from alc.intake import load_blueprint
from alc.models import Blueprint, Check, Manifest
from alc.policy import lint
from alc.runner import execute_mandate
from alc.verifier import CheckResult, Verifier

_MINIMAL_MANIFEST = Manifest(
    version=1,
    default_engine="mock",
    compute_tiers={"standard": {"mock": "mock-small"}},
    engines={"mock": {"type": "mock"}},
)


# ---------------------------------------------------------------------------
# (a) Check.flaky
# ---------------------------------------------------------------------------


class TestCheckFlakyField:
    def test_default_is_zero(self) -> None:
        check = Check(name="t", command=["true"])
        assert check.flaky == 0

    def test_negative_flaky_raises(self) -> None:
        with pytest.raises(ValidationError, match="flaky"):
            Check(name="t", command=["true"], flaky=-1)

    def test_positive_flaky_round_trips(self) -> None:
        check = Check(name="t", command=["true"], flaky=3)
        assert check.flaky == 3

    def test_front_matter_round_trip(self, tmp_path: Path) -> None:
        blueprints_dir = tmp_path / "blueprints"
        blueprints_dir.mkdir()
        (blueprints_dir / "chore.md").write_text(
            """\
---
name: chore
purpose: A standard chore blueprint.
compute_tier: standard
checks:
  - name: test
    command: ["pytest", "-q"]
    flaky: 2
---
# Workflow
Do the task.
"""
        )
        bp = load_blueprint(blueprints_dir, "chore")
        assert bp.checks[0].flaky == 2


# ---------------------------------------------------------------------------
# (b) Verifier — the flaky rerun loop
# ---------------------------------------------------------------------------


class TestVerifierFlakyRerun:
    def test_flaky_zero_never_reruns(self, tmp_path: Path) -> None:
        marker = tmp_path / "calls.txt"
        shell = f"echo x >> {marker}; exit 1"
        [result] = Verifier(timeout_s=30).run(
            [Check(name="boom", shell=shell, flaky=0)], tmp_path
        )
        assert result.passed is False
        assert len(marker.read_text().splitlines()) == 1

    def test_flaky_reruns_a_failing_check_until_it_passes(self, tmp_path: Path) -> None:
        # Fails on the first two calls, passes on the third.
        marker = tmp_path / "calls.txt"
        shell = (
            f"n=$(wc -l < {marker} 2>/dev/null || echo 0); echo x >> {marker}; "
            f"[ \"$n\" -ge 2 ]"
        )
        [result] = Verifier(timeout_s=30).run(
            [Check(name="flaky", shell=shell, flaky=3)], tmp_path
        )
        assert result.passed is True
        assert len(marker.read_text().splitlines()) == 3  # 2 failures + 1 pass

    def test_flaky_exhausted_still_fails_with_last_attempts_output(
        self, tmp_path: Path
    ) -> None:
        marker = tmp_path / "calls.txt"
        # `tr -dc 0-9` keeps only the digit so the tag is byte-identical across
        # `wc` implementations — BSD/macOS right-justifies the count with leading
        # spaces (`attempt- 3`) while GNU/Linux does not (`attempt-3`); without this
        # the assertion below is coupled to the host's `wc`.
        shell = (
            f"echo x >> {marker}; "
            f"echo attempt-$(wc -l < {marker} | tr -dc 0-9) 1>&2; exit 1"
        )
        [result] = Verifier(timeout_s=30).run(
            [Check(name="always-fails", shell=shell, flaky=2)], tmp_path
        )
        assert result.passed is False
        assert len(marker.read_text().splitlines()) == 3  # 1 initial + 2 reruns
        assert "attempt-3" in result.output  # LAST attempt's output (3rd), not the first

    def test_flaky_duration_sums_every_attempt(self, tmp_path: Path) -> None:
        [once] = Verifier(timeout_s=30).run(
            [Check(name="ok", shell="sleep 0.2; exit 1", flaky=0)], tmp_path
        )
        [thrice] = Verifier(timeout_s=30).run(
            [Check(name="ok", shell="sleep 0.2; exit 1", flaky=2)], tmp_path
        )
        assert thrice.duration_s >= once.duration_s * 2.5  # ~3x, allow scheduling slack

    def test_flaky_does_not_shrink_each_attempts_own_timeout(self, tmp_path: Path) -> None:
        # Each attempt gets the FULL timeout budget — a check that takes 0.5s per
        # attempt (well under a 1s timeout) must not time out just because it is
        # retried.
        [result] = Verifier(timeout_s=1).run(
            [Check(name="slow-but-ok", shell="sleep 0.5; exit 1", flaky=2)], tmp_path
        )
        assert result.timed_out is False


# ---------------------------------------------------------------------------
# (c) AssuranceLoop — quarantine: visible, never blocking, never repaired
# ---------------------------------------------------------------------------


def _request(workdir: Path) -> EngineRequest:
    return EngineRequest(directive="# Single-Mandate chore\nDo the task.", workdir=workdir)


def _always_fail_verifier(name: str = "flaky-suite") -> Verifier:
    class _AlwaysFailVerifier(Verifier):
        def run(self, checks, workdir, on_check_start=None, on_check_done=None):
            results = [CheckResult(name=name, passed=False, output="boom")]
            for r in results:
                if on_check_done is not None:
                    on_check_done(r)
            return results

    return _AlwaysFailVerifier()


class TestAssuranceLoopQuarantine:
    def test_quarantined_failure_does_not_fail_the_run(self, tmp_path: Path) -> None:
        loop = AssuranceLoop(
            engine=MockEngine(),
            verifier=_always_fail_verifier("flaky-suite"),
            max_repairs=3,
            quarantined=["flaky-suite"],
        )
        report = loop.run(_request(tmp_path), checks=[Check(name="flaky-suite", command=["true"])])

        assert report.success is True

    def test_quarantined_failure_still_appears_in_failed_checks(self, tmp_path: Path) -> None:
        loop = AssuranceLoop(
            engine=MockEngine(),
            verifier=_always_fail_verifier("flaky-suite"),
            max_repairs=3,
            quarantined=["flaky-suite"],
        )
        report = loop.run(_request(tmp_path), checks=[Check(name="flaky-suite", command=["true"])])

        assert "flaky-suite" in report.attempts[-1].failed_checks

    def test_quarantined_failure_marked_in_per_check_outcome(self, tmp_path: Path) -> None:
        loop = AssuranceLoop(
            engine=MockEngine(),
            verifier=_always_fail_verifier("flaky-suite"),
            max_repairs=3,
            quarantined=["flaky-suite"],
        )
        report = loop.run(_request(tmp_path), checks=[Check(name="flaky-suite", command=["true"])])

        outcome = report.attempts[-1].checks[0]
        assert outcome.name == "flaky-suite"
        assert outcome.passed is False
        assert outcome.quarantined is True

    def test_quarantined_reaches_the_check_finished_event(self, tmp_path: Path) -> None:
        """The run log must carry it too, not just the report.

        The UI reads events, not RunReport. Without `quarantined` on the event it
        shows a failed check inside a successful run with nothing joining the two
        — a green verdict over a red check, which is the one thing the UI must
        never do.
        """
        import json

        from alc.events import bind_run_log

        log = tmp_path / "run.jsonl"
        loop = AssuranceLoop(
            engine=MockEngine(),
            verifier=_always_fail_verifier("flaky-suite"),
            max_repairs=3,
            quarantined=["flaky-suite"],
        )
        with bind_run_log(log):
            loop.run(_request(tmp_path), checks=[Check(name="flaky-suite", command=["true"])])

        finished = [
            json.loads(line)
            for line in log.read_text().splitlines()
            if json.loads(line)["event"] == "check_finished"
        ]
        flaky = [e for e in finished if e["name"] == "flaky-suite"]
        assert flaky, "the quarantined check emitted no check_finished"
        assert all(e["quarantined"] is True for e in flaky)
        assert all(e["passed"] is False for e in flaky)

    def test_quarantined_failure_never_spends_a_repair_turn(self, tmp_path: Path) -> None:
        loop = AssuranceLoop(
            engine=MockEngine(),
            verifier=_always_fail_verifier("flaky-suite"),
            max_repairs=3,
            quarantined=["flaky-suite"],
        )
        report = loop.run(_request(tmp_path), checks=[Check(name="flaky-suite", command=["true"])])

        assert len(report.attempts) == 1  # one-shot: no repair was ever attempted

    def test_a_non_quarantined_failure_still_blocks_the_run(self, tmp_path: Path) -> None:
        loop = AssuranceLoop(
            engine=MockEngine(),
            verifier=_always_fail_verifier("real-check"),
            max_repairs=1,
            quarantined=["some-other-check"],
        )
        report = loop.run(_request(tmp_path), checks=[Check(name="real-check", command=["true"])])

        assert report.success is False
        assert len(report.attempts) == 2  # initial + the one repair budget allowed

    def test_no_quarantine_is_byte_identical_to_today(self, tmp_path: Path) -> None:
        loop = AssuranceLoop(
            engine=MockEngine(), verifier=_always_fail_verifier("x"), max_repairs=0
        )
        report = loop.run(_request(tmp_path), checks=[Check(name="x", command=["true"])])

        assert report.success is False
        assert report.attempts[-1].checks[0].quarantined is False


# ---------------------------------------------------------------------------
# (d) runner.py wiring — manifest.quarantined_checks reaches the loop
# ---------------------------------------------------------------------------


class TestExecuteMandateQuarantineIntegration:
    def test_quarantined_check_never_fails_the_mandate(self, tmp_path: Path, monkeypatch) -> None:
        class _AlwaysFailingEngine:
            name = "mock"

            def capabilities(self) -> Capabilities:
                return Capabilities()

            def health_check(self) -> bool:
                return True

            def run(self, request: EngineRequest) -> EngineResult:
                return EngineResult(ok=True, output_text="[mock] did nothing")

        monkeypatch.setattr(
            "alc.runner.resolve_engine", lambda name, cfg: _AlwaysFailingEngine()
        )

        manifest = Manifest(
            version=1,
            default_engine="mock",
            compute_tiers={"standard": {"mock": "mock-small"}},
            engines={"mock": {"type": "mock"}},
            quarantined_checks=["marker"],
        )
        bp = Blueprint(
            name="chore",
            purpose="p",
            workflow="# w",
            checks=[Check(name="marker", command=["test", "-f", "done.txt"])],
        )

        report = execute_mandate(
            manifest=manifest,
            blueprint=bp,
            directive="# test\ndo it",
            engine_override="mock",
            workdir=tmp_path,
        )

        assert report.success is True
        assert "marker" in report.attempts[-1].failed_checks

    def test_empty_quarantine_is_byte_identical(self, tmp_path: Path, monkeypatch) -> None:
        class _NoopEngine:
            name = "mock"

            def capabilities(self) -> Capabilities:
                return Capabilities()

            def health_check(self) -> bool:
                return True

            def run(self, request: EngineRequest) -> EngineResult:
                return EngineResult(ok=True, output_text="[mock] did nothing")

        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: _NoopEngine())

        bp = Blueprint(
            name="chore",
            purpose="p",
            workflow="# w",
            checks=[Check(name="marker", command=["test", "-f", "done.txt"])],
            max_repairs=0,
        )
        report = execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=bp,
            directive="# test\ndo it",
            engine_override="mock",
            workdir=tmp_path,
        )
        assert report.success is False


# ---------------------------------------------------------------------------
# (e) Policy Gate — permanent warn for every quarantined check
# ---------------------------------------------------------------------------


class TestPolicyQuarantineWarn:
    def test_each_quarantined_check_gets_a_warn(self) -> None:
        manifest = Manifest(
            version=1,
            default_engine="mock",
            compute_tiers={"standard": {"mock": "mock-small"}},
            engines={"mock": {"type": "mock"}},
            quarantined_checks=["flaky-a", "flaky-b"],
        )
        bp = Blueprint(
            name="chore", purpose="p", workflow="w", checks=[Check(name="smoke", command=["true"])]
        )
        violations = lint(manifest, [bp])
        matching = [v for v in violations if v.rule == "quarantined-check"]

        assert {v.message for v in matching if "flaky-a" in v.message}
        assert {v.message for v in matching if "flaky-b" in v.message}
        assert len(matching) == 2
        assert all(v.severity == "warn" for v in matching)

    def test_no_quarantine_yields_no_violation(self) -> None:
        bp = Blueprint(
            name="chore", purpose="p", workflow="w", checks=[Check(name="smoke", command=["true"])]
        )
        violations = lint(_MINIMAL_MANIFEST, [bp])
        assert [v for v in violations if v.rule == "quarantined-check"] == []

    def test_warn_persists_across_repeated_lint_calls(self) -> None:
        # "Permanent": the warn is not a one-time notice, it fires EVERY lint
        # for as long as the check is listed.
        manifest = Manifest(
            version=1,
            default_engine="mock",
            compute_tiers={"standard": {"mock": "mock-small"}},
            engines={"mock": {"type": "mock"}},
            quarantined_checks=["flaky-a"],
        )
        bp = Blueprint(
            name="chore", purpose="p", workflow="w", checks=[Check(name="smoke", command=["true"])]
        )
        first = [v.rule for v in lint(manifest, [bp]) if v.rule == "quarantined-check"]
        second = [v.rule for v in lint(manifest, [bp]) if v.rule == "quarantined-check"]
        assert first == second == ["quarantined-check"]
