# verifier.py — Runs the declared checks for a Blueprint and returns pass/fail results.
# Checks are law: nothing is reported as done until they pass or the repair budget runs out.
from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from alc.metrics import (
    append_measurement,
    latest_accepted_measurement,
    ledger_path,
    within_tolerance,
)
from alc.models import Check, MetricRecord

# Maximum characters captured from a check's combined stdout+stderr.
_MAX_OUTPUT_CHARS = 4096

# Test-runner INNER-timeout signatures. A check (e.g. `npm test`) can exit
# non-zero because its OWN runner killed a single test for exceeding THAT
# runner's per-test deadline under load — a slow/flaky check, not an assertion
# failure the engine should burn repair turns chasing. Within ALC's budget that
# looks identical to a real failure, so we read the runner's own words for it.
# These patterns are deliberately SPECIFIC (a numeric duration or an exact
# phrase): a bare word "timeout" appears in far too much unrelated output to be
# a safe signal, so it is intentionally NOT matched.
_INNER_TIMEOUT_SIGNATURES = (
    re.compile(r"Test timed out in \d+ ?ms", re.IGNORECASE),  # vitest / jest
    re.compile(r"Timeout - Async callback was not invoked", re.IGNORECASE),  # jest / mocha async
    re.compile(r"Exceeded timeout of \d+ ?ms", re.IGNORECASE),  # jest
    re.compile(r"timeout of \d+ ?ms exceeded", re.IGNORECASE),  # mocha
)

# Prepended to a failed check's output when it self-reports a runner timeout, so
# the operator (and the engine) reads the cause honestly rather than as a bug.
_INNER_TIMEOUT_NOTE = (
    "note: this check's output reports a test-runner timeout — likely a "
    "slow/flaky check under load, not an assertion failure."
)


def _reports_inner_timeout(output: str) -> bool:
    """True when *output* carries a recognizable test-runner per-test timeout
    signature — see ``_INNER_TIMEOUT_SIGNATURES``."""
    return any(pat.search(output) for pat in _INNER_TIMEOUT_SIGNATURES)


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
        self,
        max_output_chars: int = _MAX_OUTPUT_CHARS,
        timeout_s: int | None = None,
        metrics_dir: Path | None = None,
        run_id: str = "",
    ) -> None:
        # Cap on a check's combined stdout+stderr fed into the repair context.
        # Defaults to the former hardcoded value so an unset manifest is identical.
        self._max_output_chars = max_output_chars
        # Per-check wall-clock kill deadline. None => no timeout (a check can run
        # forever — the pre-timeout behavior). A hung check would otherwise freeze the
        # whole drain with NO visible cause; the timeout bounds it and surfaces why.
        self._timeout_s = timeout_s
        # Where a `metric` check's ledger lives (roadmap-phase-4.md T2). None ->
        # a metric check still runs and is judged, but nothing is recorded (no
        # project root to write into — the pre-metrics behavior for every
        # existing caller that never passes this).
        self._metrics_dir = metrics_dir
        # Free-text label recorded alongside a metric measurement (the
        # Blueprint name, at every production call site) — see MetricRecord.run.
        self._run_id = run_id
        # Per-run baseline snapshot, keyed by check name. A Verifier is
        # constructed ONCE per mandate (runner.py) / per verify_only stage
        # (flow.py) — i.e. once per run — so caching here is exactly per-run
        # scope. Captured lazily, the FIRST time this instance judges a given
        # check, and reused for every later attempt (repairs, the final
        # re-verify at assurance.py's repair-budget-exhausted path) within
        # this SAME run. Without this, a repair attempt would compare against
        # the value THIS SAME RUN just wrote a moment earlier, laundering a
        # regression into a pass by the second attempt.
        self._baseline_cache: dict[str, MetricRecord | None] = {}
        # Last value actually WRITTEN to the ledger for a given check name,
        # within this SAME run. A failing run re-measures the same check on
        # every repair attempt plus the final post-budget re-verify — an
        # UNCHANGED number would otherwise flood the ledger with duplicate
        # points for what is really one logical measurement. A value that
        # genuinely MOVED (a repair actually changed something) is still
        # recorded, so real intra-run progress stays visible.
        self._recorded: dict[str, float] = {}

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

        A ``metric`` check takes a DIFFERENT path entirely (``_run_metric``):
        tolerance already absorbs benchmark noise, so a failing measurement is
        never retried here the way a flaky command/shell check is — a rerun
        would just record extra ledger noise for a single logical measurement.
        """
        if check.metric is not None:
            return self._run_metric(check, workdir)

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
            passed = proc.returncode == 0
            # A non-zero exit whose output self-reports a test-runner timeout is a
            # slow/flaky check, not an assertion failure — mark it timed_out so it
            # flows through the SAME plumbing as ALC's own timeout ("timed out ⏱")
            # and the engine isn't misled. It still counts as NOT passed.
            inner_timeout = not passed and _reports_inner_timeout(combined)
            if inner_timeout:
                combined = f"{_INNER_TIMEOUT_NOTE}\n{combined}"
            return CheckResult(
                name=check.name,
                passed=passed,
                output=combined,
                duration_s=time.monotonic() - start,
                exit_code=proc.returncode,
                timed_out=inner_timeout,
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

    def _run_metric(self, check: Check, workdir: Path) -> CheckResult:
        """Run a ``metric`` check: execute its command, parse a single number
        off stdout, and judge that number against the metric ledger.

        "Checks are law" extends to numbers: the process's own exit code still
        gates pass/fail first (a metric command that itself fails cannot be
        trusted), and non-numeric stdout is a FAILED check with a clear
        message — never a crash. Only once a clean number is in hand does
        ``_judge_metric`` compare it against history and record it.
        """
        if check.direction is None:
            # The Policy Gate (policy.py) makes this an error that blocks `alc
            # run` before it starts; this is a defensive backstop for a
            # Verifier invoked directly (e.g. a `verify_only` flow stage).
            return CheckResult(
                name=check.name,
                passed=False,
                output=(
                    f"metric check '{check.name}' declares no 'direction' "
                    "('lower_is_better' or 'higher_is_better') — cannot be judged."
                ),
            )

        argv = ["sh", "-c", check.metric] if isinstance(check.metric, str) else check.metric
        start = time.monotonic()
        try:
            proc = subprocess.Popen(
                argv,
                cwd=workdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
        except (FileNotFoundError, OSError) as exc:
            return CheckResult(
                name=check.name,
                passed=False,
                output=f"metric check could not start: {exc}",
                duration_s=time.monotonic() - start,
            )

        try:
            stdout, stderr = proc.communicate(timeout=self._timeout_s)
        except subprocess.TimeoutExpired:
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
                    f"metric check '{check.name}' timed out after {self._timeout_s}s "
                    f"and was killed.\n{tail}"
                ),
                duration_s=time.monotonic() - start,
                exit_code=proc.returncode,
                timed_out=True,
            )

        duration_s = time.monotonic() - start
        stdout = stdout or ""
        combined = (stdout + (stderr or ""))[: self._max_output_chars]

        if proc.returncode != 0:
            return CheckResult(
                name=check.name,
                passed=False,
                output=combined or f"metric check '{check.name}' exited {proc.returncode}.",
                duration_s=duration_s,
                exit_code=proc.returncode,
            )

        try:
            value = float(stdout.strip())
        except ValueError:
            return CheckResult(
                name=check.name,
                passed=False,
                output=(
                    f"metric check '{check.name}' printed non-numeric stdout: "
                    f"{stdout.strip()[:200]!r} — a metric command must print a "
                    "single number."
                ),
                duration_s=duration_s,
                exit_code=proc.returncode,
            )

        passed, message = self._judge_metric(check, value)
        return CheckResult(
            name=check.name,
            passed=passed,
            output=message,
            duration_s=duration_s,
            exit_code=proc.returncode,
        )

    def _judge_metric(self, check: Check, value: float) -> tuple[bool, str]:
        """Compare *value* against this RUN's frozen baseline for ``check``,
        record the new value, and return ``(passed, message)``.

        The baseline is the most recent ACCEPTED measurement — see
        ``alc.metrics.latest_accepted_measurement`` — snapshotted ONCE (on
        this instance's first judgment of this check name) and reused for
        every later attempt in this run (``self._baseline_cache``): a value
        THIS run just recorded, accepted or not, must never become the
        baseline for THIS run's own next attempt. No baseline yet -> record
        and PASS (never fail a run for having no history). The measurement is
        recorded EITHER WAY — a regression's value is still visible in the
        ledger, just never selected as a future baseline (see
        ``latest_accepted_measurement``) — so the comparison always reflects
        an honest history rather than a rewritten one (roadmap-phase-4.md T2).

        A failing run re-measures the same check on every repair attempt plus
        the final post-budget re-verify; an UNCHANGED value is judged (and its
        pass/fail returned) every time, but only WRITTEN to the ledger once
        per distinct value in this run (``self._recorded``) — otherwise one
        logical measurement floods the series with identical duplicate points.
        A value that genuinely moved between attempts is still recorded.
        """
        if self._metrics_dir is None:
            return True, (
                f"metric '{check.name}' = {value:g} (no metrics_dir configured — not recorded)."
            )

        path = ledger_path(self._metrics_dir)
        if check.name not in self._baseline_cache:
            self._baseline_cache[check.name] = latest_accepted_measurement(path, check.name)
        baseline = self._baseline_cache[check.name]

        if baseline is None:
            passed = True
            message = f"metric '{check.name}' = {value:g} (first measurement — recorded as baseline)."
        else:
            passed = within_tolerance(value, baseline.value, check.direction, check.tolerance_pct)
            delta_pct = (
                (value - baseline.value) / baseline.value * 100 if baseline.value else 0.0
            )
            verdict = "within tolerance" if passed else "REGRESSION"
            message = (
                f"metric '{check.name}' = {value:g} vs baseline {baseline.value:g} "
                f"({check.direction}, tolerance={check.tolerance_pct:g}%): "
                f"delta={delta_pct:+.2f}% — {verdict}."
            )

        if self._recorded.get(check.name) != value:
            append_measurement(
                path,
                MetricRecord(
                    check=check.name, value=value, ts=time.time(), run=self._run_id, passed=passed
                ),
            )
            self._recorded[check.name] = value

        return passed, message
