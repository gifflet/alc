# schedule.py — Generates and manages the crontab entry that fires `alc tick`
# or `alc cycle NAME` on a cadence (roadmap-phase-3.md T13).
#
# `alc tick` already holds a POSIX file lock (lock.py) and exits 0 on every
# task outcome, so it is cron-safe as-is: an overlapping fire skips instead of
# double-processing, and a failed task never makes the cron job itself fail.
# This module only automates writing the line an operator would otherwise have
# to compose by hand.
#
# Pure, testable line-transformation functions (upsert/remove/list_entries) do
# not touch a real crontab; only read_crontab/write_crontab shell out to the
# `crontab` binary. Every write is marked with a distinctive comment so remove
# (and a re-run of install) can find exactly the line(s) ALC itself wrote and
# never touch anything the operator added by hand.
from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

_MARKER_PREFIX = "# alc-schedule:"
_EVERY_RE = re.compile(r"^(\d+)([mh])$")


def parse_every(spec: str) -> str:
    """Return a 5-field cron schedule expression for a ``<N>m`` / ``<N>h`` cadence.

    Only minutes and hours are supported (the roadmap's own example is
    ``--every 15m``) — a literal, not a general duration parser. Raises
    ValueError with a message fit to print straight to the operator for
    anything else: a bad unit, a non-positive N, or N out of the field's range
    (minutes must stay under 60, hours under 24 — a cron field, not a modulus).
    """
    match = _EVERY_RE.match(spec.strip())
    if not match:
        raise ValueError(
            f"unsupported --every '{spec}'; use '<N>m' or '<N>h' (e.g. '15m', '1h')"
        )
    n, unit = int(match.group(1)), match.group(2)
    if n <= 0:
        raise ValueError(f"--every must be positive, got '{spec}'")
    if unit == "m":
        if n >= 60:
            raise ValueError(
                f"minute cadence must be under 60, got '{spec}'; use hours instead"
            )
        return f"*/{n} * * * *"
    if n >= 24:
        raise ValueError(f"hour cadence must be under 24, got '{spec}'")
    return f"0 */{n} * * *"


def marker(target: str, name: str | None) -> str:
    """Return the distinctive comment tag identifying ALC's own crontab line.

    ``name`` is folded in for ``cycle`` (each loop gets its own entry); ``tick``
    has none. Matching is by SUBSTRING containment, so this exact tag is what
    both `upsert` and `remove` key on.
    """
    return f"{_MARKER_PREFIX}{target}:{name}" if name else f"{_MARKER_PREFIX}{target}"


def resolve_binary() -> list[str]:
    """Return the argv prefix that invokes `alc` from cron's bare environment.

    Prefers the installed console script, resolved to an ABSOLUTE path so
    cron's minimal PATH never has to find it. Falls back to the current
    interpreter's ``-m alc`` (also absolute) when no console script is on
    PATH — e.g. a source checkout run only via `uv run`.
    """
    found = shutil.which("alc")
    if found:
        return [str(Path(found).resolve())]
    return [sys.executable, "-m", "alc"]


def build_line(
    target: str, name: str | None, cwd: Path, cron_expr: str, binary: list[str]
) -> str:
    """Return one crontab line: cadence, `cd` into *cwd*, the resolved command, marker.

    Every token is shell-quoted (cron runs the line through ``/bin/sh -c``), so
    a project path or binary path containing spaces is still safe.
    """
    # The schedule TARGET keyword stays `cycle` (it is what the marker keys on,
    # so an entry installed before this still resolves for `list`/`remove`), but
    # the command written into cron is the current spelling. Without this, every
    # newly scheduled fire would mail the operator a deprecation notice.
    argv = (
        [*binary, "loop", name, "--once"]
        if target == "cycle" and name
        else [*binary, target, *([name] if name else [])]
    )
    command = " ".join(shlex.quote(a) for a in argv)
    return f"{cron_expr} cd {shlex.quote(str(cwd))} && {command} {marker(target, name)}"


def has_crontab() -> bool:
    """Return True when a `crontab` binary is on PATH."""
    return shutil.which("crontab") is not None


def read_crontab() -> list[str]:
    """Return the current user crontab's lines.

    Empty when there is no crontab yet (`crontab -l` exits non-zero with "no
    crontab for user") or the read otherwise fails — both degrade to "no
    entries" rather than raising, mirroring the rest of the control plane's
    never-crash-the-operation stance around missing git/crontab state.
    """
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    except FileNotFoundError:
        return []
    if result.returncode != 0:
        return []
    return result.stdout.splitlines()


def write_crontab(lines: list[str]) -> bool:
    """Replace the user crontab with *lines* (empty clears it). Return success."""
    body = "\n".join(lines)
    if body:
        body += "\n"
    try:
        result = subprocess.run(
            ["crontab", "-"], input=body, capture_output=True, text=True
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0


def upsert(lines: list[str], target: str, name: str | None, new_line: str) -> list[str]:
    """Return *lines* with any prior entry for target/name replaced by *new_line*.

    Idempotent: install run twice ends with exactly ONE entry. Matches purely
    by the marker comment, so a line the operator wrote by hand — even one
    that happens to also run `alc tick` — is left untouched unless it carries
    ALC's own marker.
    """
    tag = marker(target, name)
    kept = [line for line in lines if tag not in line]
    return [*kept, new_line]


def remove(lines: list[str], target: str, name: str | None) -> list[str]:
    """Return *lines* with target/name's entry (if any) dropped. Same tag match as `upsert`."""
    tag = marker(target, name)
    return [line for line in lines if tag not in line]


def list_entries(lines: list[str]) -> list[str]:
    """Return only the crontab lines ALC itself wrote (carry the marker prefix)."""
    return [line for line in lines if _MARKER_PREFIX in line]
