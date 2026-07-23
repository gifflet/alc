# verifier.py — Runs the declared checks for a Blueprint and returns pass/fail results.
# Checks are law: nothing is reported as done until they pass or the repair budget runs out.
from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from alc.models import Check

# Maximum characters captured from a check's combined stdout+stderr.
_MAX_OUTPUT_CHARS = 4096


@dataclass
class CheckResult:
    """Result of running a single check command."""

    name: str
    passed: bool
    output: str  # combined stdout + stderr, truncated to _MAX_OUTPUT_CHARS
    duration_s: float = 0.0  # wall-clock time spent running this check (all attempts)
    exit_code: int | None = None  # the process's return code; None if it never started
    timed_out: bool = False  # the check was KILLED for exceeding the timeout


class Verifier:
    """Runs Blueprint checks as subprocesses and collects pass/fail results."""

    def __init__(
        self, max_output_chars: int = _MAX_OUTPUT_CHARS, timeout_s: int | None = None
    ) -> None:
        # Cap on a check's combined stdout+stderr fed into the repair context.
        # Defaults to the former hardcoded value so an unset manifest is identical.
        self._max_output_chars = max_output_chars
        # Per-check wall-clock kill deadline. None => no timeout (a check can run
        # forever — the pre-timeout behavior). A hung check would otherwise freeze the
        # whole drain with NO visible cause; the timeout bounds it and surfaces why.
        self._timeout_s = timeout_s

    def run(
        self,
        checks: list[Check],
        workdir: Path,
        on_check_start: Callable[[str], None] | None = None,
        on_check_done: Callable[[CheckResult], None] | None = None,
    ) -> list[CheckResult]:
        """Execute every check command in workdir and return results.

        ``on_check_start(name)`` fires BEFORE each check and ``on_check_done(result)``
        AFTER it — the control plane uses them to emit real-time run-log events so an
        operator sees WHICH check is running (and whether it timed out), instead of a
        silent freeze while a hung check blocks the drain.

        Args:
            checks: List of Check objects from the Blueprint.
            workdir: Directory in which to run the check commands.
            on_check_start: Optional callback invoked with each check's name before it runs.
            on_check_done: Optional callback invoked with each CheckResult as it completes.

        Returns:
            One CheckResult per check, in order.
        """
        results: list[CheckResult] = []
        for check in checks:
            if on_check_start is not None:
                on_check_start(check.name)
            result = self._run_one(check, workdir)
            if on_check_done is not None:
                on_check_done(result)
            results.append(result)
        return results

    def _run_one(self, check: Check, workdir: Path) -> CheckResult:
        """Run ``check``, bounded by the timeout; kill its whole process group on hang.

        When ``check.flaky`` is set, a FAILING attempt is re-run up to that many
        times — seconds spent here, in the Verifier, are cheap next to an engine
        repair turn. The first PASS wins. Each attempt gets its OWN full
        ``timeout_s`` budget: a flaky rerun is a fresh process, not a continuation
        of a timed-out one, so the timeout is never divided or shrunk across
        retries. The returned ``duration_s`` is the SUM of every attempt's wall
        time — the check's real cost, visible in per-check history (`alc checks
        history`) — while ``passed``/``output``/``exit_code``/``timed_out``
        reflect only the LAST (deciding) attempt.
        """
        result = self._run_once(check, workdir)
        total_duration = result.duration_s
        retries_left = check.flaky
        while not result.passed and retries_left > 0:
            retries_left -= 1
            result = self._run_once(check, workdir)
            total_duration += result.duration_s
        return replace(result, duration_s=total_duration)

    def _run_once(self, check: Check, workdir: Path) -> CheckResult:
        """Run ``check`` exactly ONE time and return that single attempt's result."""
        # The Check model guarantees exactly one of shell/command is set.
        argv = ["sh", "-c", check.shell] if check.shell is not None else check.command
        start = time.monotonic()
        try:
            proc = subprocess.Popen(
                argv,
                cwd=workdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,  # own group so children are reapable on timeout
            )
        except (FileNotFoundError, OSError) as exc:
            return CheckResult(
                name=check.name,
                passed=False,
                output=f"check could not start: {exc}",
                duration_s=time.monotonic() - start,
            )

        try:
            stdout, stderr = proc.communicate(timeout=self._timeout_s)
            combined = ((stdout or "") + (stderr or ""))[: self._max_output_chars]
            return CheckResult(
                name=check.name,
                passed=(proc.returncode == 0),
                output=combined,
                duration_s=time.monotonic() - start,
                exit_code=proc.returncode,
            )
        except subprocess.TimeoutExpired:
            # Kill the WHOLE process group so a child (e.g. `pnpm` -> `node --test`)
            # can't linger holding the worktree open. Reap, then surface the cause.
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            try:
                stdout, stderr = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                stdout, stderr = "", ""
            tail = ((stdout or "") + (stderr or ""))[: self._max_output_chars]
            return CheckResult(
                name=check.name,
                passed=False,
                output=(
                    f"check '{check.name}' timed out after {self._timeout_s}s "
                    f"and was killed.\n{tail}"
                ),
                duration_s=time.monotonic() - start,
                exit_code=proc.returncode,
                timed_out=True,
            )
