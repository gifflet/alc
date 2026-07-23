# assurance.py — The Assurance Loop: Act -> Verify -> Repair.
# Drives the engine through bounded repair cycles until checks pass or budget is exhausted.
# This is the core enforcement mechanism: checks are law.
from __future__ import annotations

import sys
from collections.abc import Callable
from fnmatch import fnmatch

from alc.engine import Engine, EngineRequest, Usage
from alc.events import emit
from alc.models import AttemptRecord, Check, RunReport, Scorecard
from alc.prompts import _REPAIR_TEMPLATE
from alc.verifier import CheckResult, Verifier


def _usage_payload(usage: Usage) -> dict[str, int | float | None] | None:
    """Return a JSON-friendly usage dict, or None when nothing was reported."""
    if (
        usage.input_tokens is None
        and usage.output_tokens is None
        and usage.cost_usd is None
    ):
        return None
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cost_usd": usage.cost_usd,
    }


def _accumulate_usage(total: Usage | None, result_usage: Usage) -> Usage | None:
    """Fold one attempt's EngineResult.usage into the running per-run total.

    None-safe: a missing field on either side is treated as 0 for the sum, but a
    field stays None until at least one attempt actually reports it. When nothing
    has ever been reported the running total stays None (so the loop can WARN
    instead of silently reading a usage of zero).
    """
    reported = (
        result_usage.input_tokens is not None
        or result_usage.output_tokens is not None
        or result_usage.cost_usd is not None
    )
    if not reported:
        return total
    if total is None:
        total = Usage()

    def _add(a: int | float | None, b: int | float | None):
        if a is None and b is None:
            return None
        return (a or 0) + (b or 0)

    return Usage(
        input_tokens=_add(total.input_tokens, result_usage.input_tokens),
        output_tokens=_add(total.output_tokens, result_usage.output_tokens),
        cost_usd=_add(total.cost_usd, result_usage.cost_usd),
    )


class AssuranceLoop:
    """Orchestrates Act -> Verify -> Repair for a single Single-Mandate run.

    Args:
        engine: An Engine instance (resolved by the registry).
        verifier: A Verifier instance for running checks.
        max_repairs: Maximum number of repair attempts after the initial act.
                     Total engine turns = 1 (initial) + max_repairs.
        repair_template: The repair addendum template with a single ``{failures}``
                     placeholder. Defaults to the embedded ``repair`` prompt;
                     execute_mandate passes the resolved override when present.
        protect: Glob patterns (fnmatch, workdir-relative) an Act must never
                     touch. After each attempt, ``changed_files()`` is crossed
                     against these globs; any hit becomes a synthetic failed
                     check (``protected-paths``) that feeds the same repair
                     addendum as a real check failure. Empty (default) -> no-op.
        changed_files: Callable returning the paths changed so far in the run's
                     workdir, called once per attempt. Bound by the caller
                     (runner.py) so this loop never gains a git dependency of
                     its own. Ignored when ``protect`` is empty.
    """

    def __init__(
        self,
        engine: Engine,
        verifier: Verifier,
        max_repairs: int = 3,
        repair_template: str = _REPAIR_TEMPLATE,
        protect: list[str] | None = None,
        changed_files: Callable[[], list[str]] | None = None,
    ) -> None:
        self._engine = engine
        self._verifier = verifier
        self._max_repairs = max_repairs
        self._repair_template = repair_template
        self._protect = protect or []
        self._changed_files = changed_files

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
        usage_total: Usage | None = None

        for attempt_index in range(self._max_repairs + 1):
            # --- Act ---
            print(
                f"→ Act (attempt {attempt_index + 1}/{self._max_repairs + 1})…",
                file=sys.stderr,
                flush=True,
            )
            emit("act_started", attempt=attempt_index)
            result = self._engine.run(current_request)
            last_output = result.output_text
            usage_total = _accumulate_usage(usage_total, result.usage)

            act_usage = _usage_payload(result.usage)
            if act_usage is not None:
                emit("act_finished", attempt=attempt_index, ok=result.ok, usage=act_usage)
            else:
                emit("act_finished", attempt=attempt_index, ok=result.ok)

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
                    usage=usage_total,
                )

            # --- Verify ---
            print(f"→ Verify ({len(checks)} check(s))…", file=sys.stderr, flush=True)
            emit(
                "verify_started",
                attempt=attempt_index,
                checks=[c.name for c in checks],
            )
            # Emit check_started/check_finished in REAL TIME (per check) so a slow or
            # HUNG check is visible as it runs — which check, and whether it timed out
            # — instead of a silent freeze while it blocks the drain.
            check_results = self._verifier.run(
                checks,
                request.workdir,
                on_check_start=lambda name, a=attempt_index: emit(
                    "check_started", attempt=a, name=name
                ),
                on_check_done=lambda cr, a=attempt_index: emit(
                    "check_finished",
                    attempt=a,
                    name=cr.name,
                    passed=cr.passed,
                    output_tail=cr.output,
                    timed_out=cr.timed_out,
                ),
            )
            protect_violation = self._check_protect()
            if protect_violation is not None:
                check_results = [*check_results, protect_violation]
            failed = [cr for cr in check_results if not cr.passed]

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
                    usage=usage_total,
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
            usage=usage_total,
        )

    def _check_protect(self) -> CheckResult | None:
        """Return a synthetic failed CheckResult when this attempt touched a
        protected path, else None.

        Deterministic and engine-agnostic — fnmatch only, no git/subprocess
        knowledge here. A no-op when ``protect`` is empty or no ``changed_files``
        callable was bound (the caller degrades to None outside a git repo).
        """
        if not self._protect or self._changed_files is None:
            return None
        hits = [
            path
            for path in self._changed_files()
            if any(fnmatch(path, glob) for glob in self._protect)
        ]
        if not hits:
            return None
        hit_list = "\n".join(f"  - {path}" for path in hits)
        return CheckResult(
            name="protected-paths",
            passed=False,
            output=(
                "This attempt edited path(s) protected by the Blueprint's "
                f"`protect:` globs — revert them:\n{hit_list}"
            ),
        )

    def _build_failure_section(self, failed_checks) -> str:
        """Build the repair addendum appended to the directive on failure.

        ALC pre-renders the per-check ```-fenced blocks into ``{failures}`` and
        the ``repair`` template controls the surrounding framing.
        """
        failures = "".join(
            f"\n### Check: {cr.name}\n```\n{cr.output.strip()}\n```\n"
            for cr in failed_checks
        )
        return self._repair_template.format(failures=failures)
