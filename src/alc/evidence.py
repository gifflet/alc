# evidence.py — e2e evidence capture for a `needs_service` run (roadmap-phase-5.md T6).
#
# A `needs_service` Blueprint proves the app STARTS (health poll) and its checks
# PASS, but keeps no record that the golden path actually worked — no screenshot,
# no health-poll log. When a Blueprint also declares `capture:` (a shell command
# the operator supplies — a script that saves a screenshot, curls an endpoint
# into a file, whatever), this runs it once the health poll has already proven
# the app reachable, then collects whatever landed under the run's artifacts
# directory. The health-poll log RuntimeService captures — thrown away today —
# is persisted alongside it.
#
# Same never-raise contract as commit.py/notify.py: a failing/missing capture
# command warns (returned, not printed — the caller has a RunReport to attach
# it to) and the run carries on. `capture:` is purely additive: a Blueprint
# that declares none never calls this module at all.
#
# stdlib only, no new dependency — same principle as the Phase 2 security
# scanners: ALC orchestrates the operator's tool, it does not become it.
from __future__ import annotations

import subprocess
from pathlib import Path

_HEALTH_LOG_NAME = "health-poll.log"


def capture_evidence(
    command: str,
    health_log: str,
    workdir: Path,
    artifacts_dir: Path,
    project_root: Path,
    env: dict[str, str],
    timeout_s: int,
) -> tuple[list[str], list[str]]:
    """Persist *health_log*, run *command*, and collect what it produced.

    Args:
        command: The Blueprint's `capture:` shell command (run via `sh -c`).
        health_log: RuntimeService's full captured stdout+stderr for this run.
        workdir: cwd for *command* — the run's effective workdir.
        artifacts_dir: This run's own artifacts directory
            (``<project_root>/<manifest.artifacts_dir>/<run stem>``); created
            here if absent.
        project_root: Root the returned artifact paths are relative to.
        env: Environment for *command* (already carries ALC_BASE_URL/PORT/…);
            this adds `ALC_ARTIFACTS_DIR` pointing at *artifacts_dir* so the
            command has an absolute, run-scoped place to write to regardless
            of *workdir*.
        timeout_s: Wall-clock cap on *command* (manifest.check_timeout_s).

    Returns:
        (artifact_paths, warnings). ``artifact_paths`` are project-root-relative
        POSIX strings for every file under *artifacts_dir* afterward, sorted —
        the persisted health log plus anything *command* wrote, regardless of
        whether *command* itself succeeded. ``warnings`` is empty on a clean
        run; a directory that cannot be created is fatal to this call alone
        (nothing to attach) and short-circuits before the command ever runs.
    """
    try:
        artifacts_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return [], [f"capture: could not create artifacts directory {artifacts_dir}: {exc}"]

    warnings: list[str] = []

    try:
        (artifacts_dir / _HEALTH_LOG_NAME).write_text(health_log, encoding="utf-8")
    except OSError as exc:
        warnings.append(f"capture: could not persist the health-poll log: {exc}")

    proc_env = {**env, "ALC_ARTIFACTS_DIR": str(artifacts_dir)}
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(workdir),
            env=proc_env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        if result.returncode != 0:
            warnings.append(
                f"capture command exited {result.returncode}: {result.stderr.strip()[:500]}"
            )
    except subprocess.TimeoutExpired:
        warnings.append(f"capture command timed out after {timeout_s}s")
    except OSError as exc:
        warnings.append(f"capture command failed to start: {exc}")

    artifact_paths = sorted(
        p.relative_to(project_root).as_posix() for p in artifacts_dir.rglob("*") if p.is_file()
    )
    return artifact_paths, warnings
