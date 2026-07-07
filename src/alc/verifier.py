# verifier.py — Runs the declared checks for a Blueprint and returns pass/fail results.
# Checks are law: nothing is reported as done until they pass or the repair budget runs out.
from __future__ import annotations

import subprocess
from dataclasses import dataclass
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


class Verifier:
    """Runs Blueprint checks as subprocesses and collects pass/fail results."""

    def run(self, checks: list[Check], workdir: Path) -> list[CheckResult]:
        """Execute every check command in workdir and return results.

        Args:
            checks: List of Check objects from the Blueprint.
            workdir: Directory in which to run the check commands.

        Returns:
            One CheckResult per check, in order.
        """
        results: list[CheckResult] = []
        for check in checks:
            # The Check model guarantees exactly one of shell/command is set.
            argv = ["sh", "-c", check.shell] if check.shell is not None else check.command
            proc = subprocess.run(
                argv,
                cwd=workdir,
                capture_output=True,
                text=True,
            )
            combined = (proc.stdout + proc.stderr)[:_MAX_OUTPUT_CHARS]
            results.append(
                CheckResult(
                    name=check.name,
                    passed=(proc.returncode == 0),
                    output=combined,
                )
            )
        return results
