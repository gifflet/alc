# assurance.py — The Assurance Loop: Act -> Verify -> Repair.
# Drives the engine through bounded repair cycles until checks pass or budget is exhausted.
# This is the core enforcement mechanism: checks are law.
from __future__ import annotations

import sys

from alc.engine import Engine, EngineRequest
from alc.models import AttemptRecord, Blueprint, Check, RunReport, Scorecard
from alc.verifier import Verifier


class AssuranceLoop:
    """Orchestrates Act -> Verify -> Repair for a single Single-Mandate run.

    Args:
        engine: An Engine instance (resolved by the registry).
        verifier: A Verifier instance for running checks.
        max_repairs: Maximum number of repair attempts after the initial act.
                     Total engine turns = 1 (initial) + max_repairs.
    """

    def __init__(self, engine: Engine, verifier: Verifier, max_repairs: int = 3) -> None:
        self._engine = engine
        self._verifier = verifier
        self._max_repairs = max_repairs

    def run(self, request: EngineRequest, checks: list[Check]) -> RunReport:
        """Execute the loop and return a RunReport with a Scorecard.

        Attempt 0: engine.run(request) then verify.
        If any check fails and repair budget remains, compose a repair directive
        (original directive + failed-check output) and loop back.

        Args:
            request: The initial EngineRequest composed by the Mandate Runner.
            checks: Blueprint checks that must all pass for success.

        Returns:
            RunReport describing the full attempt history and Scorecard.
        """
        attempts: list[AttemptRecord] = []
        current_request = request
        last_output = ""

        for attempt_index in range(self._max_repairs + 1):
            # --- Act ---
            print(
                f"→ Act (attempt {attempt_index + 1}/{self._max_repairs + 1})…",
                file=sys.stderr,
                flush=True,
            )
            result = self._engine.run(current_request)
            last_output = result.output_text

            # The engine itself failed to run (bad invocation, missing binary,
            # auth error, timeout). Repairing is futile — surface the error and
            # stop, instead of looping silently and burying the failure.
            if not result.ok:
                print(
                    f"  ✗ engine failed to run: {result.output_text.strip()[:500]}",
                    file=sys.stderr,
                    flush=True,
                )
                attempts.append(
                    AttemptRecord(index=attempt_index, engine_ok=False, failed_checks=[])
                )
                return RunReport(
                    blueprint=request.directive[:40],
                    engine=self._engine.name,
                    success=False,
                    attempts=attempts,
                    scorecard=Scorecard(span=0, passes=attempt_index + 1, streak=0, touch=0),
                    output_text=result.output_text,
                )

            # --- Verify ---
            print(f"→ Verify ({len(checks)} check(s))…", file=sys.stderr, flush=True)
            check_results = self._verifier.run(checks, request.workdir)
            failed = [cr for cr in check_results if not cr.passed]
            passed_names = [cr.name for cr in check_results if cr.passed]

            attempts.append(
                AttemptRecord(
                    index=attempt_index,
                    engine_ok=result.ok,
                    failed_checks=[cr.name for cr in failed],
                )
            )

            if not failed:
                # All checks pass — success.
                print("  ✓ all checks passed", file=sys.stderr, flush=True)
                scorecard = Scorecard(
                    span=len(check_results),
                    passes=attempt_index + 1,
                    streak=1 if attempt_index == 0 else 0,
                    touch=0,
                )
                return RunReport(
                    blueprint=request.directive[:40],  # abbreviated label
                    engine=self._engine.name,
                    success=True,
                    attempts=attempts,
                    scorecard=scorecard,
                    output_text=last_output,
                )

            print(
                f"  ✗ checks failed: {', '.join(cr.name for cr in failed)}",
                file=sys.stderr,
                flush=True,
            )

            # Repair budget exhausted?
            if attempt_index >= self._max_repairs:
                break

            print("  → repairing…", file=sys.stderr, flush=True)
            # --- Repair: compose a new directive with failure context ---
            failure_section = self._build_failure_section(failed)
            repair_directive = current_request.directive + failure_section
            current_request = EngineRequest(
                directive=repair_directive,
                workdir=request.workdir,
                model=request.model,
                allowed_tools=request.allowed_tools,
                denied_tools=request.denied_tools,
                system_append=request.system_append,
                timeout_s=request.timeout_s,
                env=request.env,
                permission_mode=request.permission_mode,
            )

        # All attempts exhausted without passing all checks.
        final_check_results = self._verifier.run(checks, request.workdir)
        final_passed = sum(1 for cr in final_check_results if cr.passed)

        scorecard = Scorecard(
            span=final_passed,
            passes=len(attempts),
            streak=0,
            touch=0,
        )
        return RunReport(
            blueprint=request.directive[:40],
            engine=self._engine.name,
            success=False,
            attempts=attempts,
            scorecard=scorecard,
            output_text=last_output,
        )

    @staticmethod
    def _build_failure_section(failed_checks) -> str:
        """Build the repair addendum appended to the directive on failure."""
        lines = [
            "\n\n---\n## Repair Required\n",
            "The following checks FAILED. Fix all issues and try again.\n",
        ]
        for cr in failed_checks:
            lines.append(f"\n### Check: {cr.name}\n```\n{cr.output.strip()}\n```\n")
        return "".join(lines)
