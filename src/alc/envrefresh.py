# envrefresh.py — Refresh the environment when a run bumps a dependency manifest.
#
# "Checks are law" must hold for dependency bumps too. A `link:` provision shares
# the operator's already-installed node_modules into every worktree; when a run
# EDITS package.json (a breaking major bump, say), the checks that follow would
# otherwise run against those STALE, already-installed packages — a breaking change
# passes green because type-check/build/test never saw the new versions. This leaf
# closes that false green: when a run changed a file matching a provision's
# `when_changed` globs, it runs that provision's `refresh` install (in an ISOLATED
# deps dir — see worktree.materialize_isolated) BEFORE the Verifier, so the checks
# test the NEW versions.
#
# SRP: this module only DECIDES whether to refresh and RUNS the install. It owns no
# git knowledge (the caller binds a `changed_files` callable, exactly as `protect`
# and the check-config guard do) and no assurance-loop control flow (assurance.py
# calls the closure between Act and Verify). Imports are all leaves relative to the
# runner — stdlib plus models / verifier.CheckResult / events.emit / worktree — so
# there is no import cycle.
from __future__ import annotations

import hashlib
import os
import signal
import subprocess
import time
from collections.abc import Callable, Sequence
from fnmatch import fnmatch
from pathlib import Path

from alc import worktree
from alc.events import emit
from alc.models import ProvisionSpec
from alc.verifier import CheckResult

# The synthetic check name a refresh FAILURE surfaces under — a stable label the
# AssuranceLoop records and the repair addendum quotes (mirrors "protected-paths"
# and "check-config-integrity").
_REFRESH_CHECK_NAME = "env-refresh"

# Absent-marker mixed into the content digest for a matched path that cannot be
# read (missing, dangling, or a directory). Keeps the digest well-defined so the
# memo distinguishes "the file is gone" from "the file has these bytes".
_ABSENT_MARKER = b"\x00__alc_absent__\x00"


def has_refresh(provisions: Sequence[ProvisionSpec]) -> bool:
    """Return True when any provision spec declares a ``refresh``.

    The caller (runner.py) binds the closure only when this is True, so a manifest
    whose provisions declare no refresh leaves the AssuranceLoop byte-identical.
    """
    return any(spec.refresh is not None for spec in provisions)


def _content_digest(workdir: Path, paths: Sequence[str]) -> str:
    """SHA-256 over the sorted ``(path, file-bytes | absent-marker)`` of *paths*.

    Order-independent (paths are sorted) so the same set of files hashes identically
    regardless of the order ``changed_files`` returns them. A path that cannot be
    read hashes with ``_ABSENT_MARKER`` rather than raising.
    """
    h = hashlib.sha256()
    for rel in sorted(paths):
        h.update(rel.encode("utf-8", "surrogatepass"))
        h.update(b"\x00")
        try:
            h.update((workdir / rel).read_bytes())
        except (OSError, ValueError):
            h.update(_ABSENT_MARKER)
        h.update(b"\x00")
    return h.hexdigest()


def _run_refresh_command(
    argv: list[str], workdir: Path, timeout_s: int | None, max_output_chars: int
) -> CheckResult:
    """Run *argv* in *workdir* and return a CheckResult (``passed`` == exited 0).

    Mirrors ``verifier.Verifier._run_once`` exactly: a new session so the whole
    process group is reapable, output truncated to *max_output_chars*, and the
    entire group killed with ``os.killpg`` on timeout so a child (npm -> node) can't
    linger holding the worktree open. Always returns a CheckResult named
    ``env-refresh`` — the closure maps a passing one to "no failure" (None).
    """
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
            name=_REFRESH_CHECK_NAME,
            passed=False,
            output=f"env refresh could not start: {exc}",
            duration_s=time.monotonic() - start,
        )

    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
        combined = ((stdout or "") + (stderr or ""))[:max_output_chars]
        passed = proc.returncode == 0
        if not passed and not combined:
            combined = f"env refresh '{' '.join(argv)}' exited {proc.returncode}."
        return CheckResult(
            name=_REFRESH_CHECK_NAME,
            passed=passed,
            output=combined,
            duration_s=time.monotonic() - start,
            exit_code=proc.returncode,
        )
    except subprocess.TimeoutExpired:
        # Kill the WHOLE process group so a child can't linger, then reap and surface.
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        tail = ((stdout or "") + (stderr or ""))[:max_output_chars]
        return CheckResult(
            name=_REFRESH_CHECK_NAME,
            passed=False,
            output=(
                f"env refresh timed out after {timeout_s}s and was killed.\n{tail}"
            ),
            duration_s=time.monotonic() - start,
            exit_code=proc.returncode,
            timed_out=True,
        )


def make_env_refresh(
    provisions: Sequence[ProvisionSpec],
    workdir: Path,
    changed_files: Callable[[], list[str]],
    timeout_s: int | None,
    max_output_chars: int,
) -> Callable[[], CheckResult | None]:
    """Build the post-Act/pre-Verify env-refresh closure the AssuranceLoop calls.

    The returned closure carries per-run memo state (a content digest per refresh
    spec) so a repeated repair attempt does not reinstall when nothing dep-relevant
    changed. Each call, for every provision that declares a ``refresh``:

      1. ``matched`` = the paths ``changed_files()`` returns that match this spec's
         ``when_changed`` globs. Empty -> skip (a non-deps run does nothing beyond
         listing its changed files — the scope guard).
      2. If the matched files' content digest equals this spec's last SUCCESSFUL
         refresh digest, skip — the environment is already fresh for this content
         (don't reinstall on every repair attempt).
      3. If ``workdir / spec.path`` is a SYMLINK, COW-clone it into place first
         (materialize_isolated) so the install cannot write through the link into
         the operator's shared deps. A copy:/clone: dst is already isolated; a
         missing/dangling dst is left for the install to create fresh.
      4. Run the ``refresh`` argv (cwd=workdir), emitting env_refresh_started /
         env_refresh_finished.
      5. On success, RE-LIST ``changed_files()`` and store the digest of the
         POST-install matched set (the install updates the lockfile — itself a
         ``when_changed`` file — so hashing post-install prevents an
         install -> lockfile-changed -> reinstall loop). On failure, return the
         failed CheckResult WITHOUT storing the memo (so the next attempt retries).

    Returns None overall when nothing needed refreshing; the first failing spec's
    failed CheckResult otherwise (short-circuit — checks against a broken env are a
    false signal, so the caller skips the Verifier this attempt).
    """
    refresh_specs = [spec for spec in provisions if spec.refresh is not None]
    # Per-spec digest of the last SUCCESSFUL refresh's POST-install state, keyed by
    # the spec's index. Persists across calls (repair attempts) for this one run.
    last_success_digest: dict[int, str] = {}

    def _refresh() -> CheckResult | None:
        for i, spec in enumerate(refresh_specs):
            matched = [
                path
                for path in changed_files()
                if any(fnmatch(path, glob) for glob in spec.when_changed)
            ]
            if not matched:
                continue  # nothing dep-relevant changed for this spec

            digest = _content_digest(workdir, matched)
            if last_success_digest.get(i) == digest:
                continue  # already refreshed for exactly this content

            # Materialize isolation lazily: a symlinked dst is COW-cloned so the
            # mutating install writes into the worktree's OWN copy, never through
            # the link into the operator's shared deps. A copy:/clone: dst (already
            # isolated) and a missing/dangling dst are both left untouched.
            dst = workdir / spec.path
            if dst.is_symlink():
                worktree.materialize_isolated(dst)

            emit("env_refresh_started", path=spec.path, command=spec.refresh)
            result = _run_refresh_command(
                spec.refresh, workdir, timeout_s, max_output_chars  # type: ignore[arg-type]
            )
            emit(
                "env_refresh_finished",
                path=spec.path,
                ok=result.passed,
                duration_s=result.duration_s,
                exit_code=result.exit_code,
                timed_out=result.timed_out,
            )
            if not result.passed:
                # Do NOT store the memo — the next attempt must retry the install.
                return result

            # Success: hash the POST-install state so the lockfile the install just
            # wrote does not re-trigger this same refresh on the next attempt.
            post_matched = [
                path
                for path in changed_files()
                if any(fnmatch(path, glob) for glob in spec.when_changed)
            ]
            last_success_digest[i] = _content_digest(workdir, post_matched)

        return None

    return _refresh
