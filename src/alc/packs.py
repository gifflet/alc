# packs.py — Archetype Pack registry: what `alc team hire <archetype>` writes.
#
# A pack is a plain dict {relative path: content}, parameterised by the stacks
# detect_stacks() found. PACKS is a data table (archetype -> file-generator); no
# class hierarchy, no plugin system. This module is pure — no filesystem I/O.
# Writing, existence checks, and the overwrite-refusal contract all live in
# cli.py's `alc team hire` (mirroring how scaffold.py's templates stay separate
# from scaffold()'s own disk-writing).
from __future__ import annotations

from collections.abc import Callable

# ---------------------------------------------------------------------------
# Builder pack — test authoring, live e2e QA, and a hardened ship flow.
# ---------------------------------------------------------------------------

_BUILDER_TEST = """\
---
name: test
purpose: Author tests that cover the behavior a change just introduced.
compute_tier: standard
{check_set_line}checks:
  # A pack Blueprint must never depend on check_set alone — an empty check_set
  # (no stack tooling on PATH at hire time) would otherwise resolve to zero
  # checks and fail Policy Gate rule 1. This inline check keeps it lint-clean.
  - name: smoke
    command: ["true"]
report:
  format: json
  schema:
    status: string
    summary: string
archetype: builder
---

## Test Workflow

1. Read the task description and the recent diff to find the behavior that changed.
2. Write or extend tests that exercise it: the happy path and at least one edge case.
3. Run the checks — including the stack's full check_set, when declared — to
   confirm the new tests pass alongside the existing suite.
4. Output a JSON report matching the schema:
   ```json
   {{"status": "ok", "summary": "<one sentence describing the tests added>"}}
   ```
"""

_BUILDER_QA = """\
---
name: qa
purpose: Verify the change end-to-end against a live instance of the service.
compute_tier: standard
needs_service: true
{check_set_line}checks:
  # Hits the live service ALC started for this run ($ALC_BASE_URL) — the inline
  # check that keeps this Blueprint lint-clean even when check_set resolves empty.
  - name: e2e-smoke
    shell: 'curl -sf "$ALC_BASE_URL"'
report:
  format: json
  schema:
    status: string
    summary: string
archetype: builder
---

## QA Workflow

1. Read the task description to understand the user-facing behavior to verify.
2. Exercise it against the live service at $ALC_BASE_URL (the app ALC started
   for this run) — never mock the service.
3. Run the checks to confirm the change behaves correctly end-to-end.
4. Output a JSON report matching the schema:
   ```json
   {{"status": "ok", "summary": "<one sentence describing what was verified>"}}
   ```
"""

_BUILDER_SHIP_HARDENED = """\
name: ship-hardened
description: Plan a change, build it, harden it with tests, then a pure verification gate.
stages:
  - name: plan
    blueprint: plan
  - name: build
    blueprint: feature
  - name: harden
    blueprint: test
  - name: gate
    blueprint: test
    verify_only: true
"""


def _check_set_line(
    stacks: list[tuple[str, str, list[tuple[str, list[str]]]]],
) -> str:
    """Return a `check_set: <name>\\n` front-matter line for the primary detected stack.

    Empty string when no stack was detected — a Blueprint must never reference a
    check_set name the Manifest doesn't declare (Policy Gate rule 7). Uses the
    FIRST detected stack, the same single-stack precedence scaffold.detect_stack()
    uses for the default blueprints: one real battery per Blueprint, with the full
    multi-stack coverage living in check_sets itself.
    """
    if not stacks:
        return ""
    _label, set_name, _checks = stacks[0]
    return f"check_set: {set_name}\n"


def _builder_files(
    stacks: list[tuple[str, str, list[tuple[str, list[str]]]]],
) -> dict[str, str]:
    """Build the Builder pack: test authoring, live e2e QA, and a hardened ship flow."""
    check_set_line = _check_set_line(stacks)
    return {
        ".alc/blueprints/test.md": _BUILDER_TEST.format(check_set_line=check_set_line),
        ".alc/blueprints/qa.md": _BUILDER_QA.format(check_set_line=check_set_line),
        ".alc/flows/ship-hardened.yaml": _BUILDER_SHIP_HARDENED,
    }


# Archetype name -> file-generator. Packs a later wave adds (sweeper, maintainer,
# grower, prototyper) are simply absent from this table until their wave lands;
# `alc team hire` reports that plainly (see pack_files' KeyError) instead of failing.
PACKS: dict[
    str, Callable[[list[tuple[str, str, list[tuple[str, list[str]]]]]], dict[str, str]]
] = {
    "builder": _builder_files,
}


def pack_files(
    archetype: str,
    stacks: list[tuple[str, str, list[tuple[str, list[str]]]]],
) -> dict[str, str]:
    """Return {relative path: content} for *archetype*, parameterised by *stacks*.

    Args:
        archetype: Pack name — must be a key of PACKS.
        stacks: detect_stacks() output (label, check_set name, checks per stack) —
            used to pick the primary check_set a pack Blueprint opts into.

    Returns:
        {path relative to the project root: file content}, e.g.
        {".alc/blueprints/test.md": "---\\nname: test\\n..."}.

    Raises:
        KeyError: If *archetype* is not (yet) a registered pack.
    """
    try:
        build = PACKS[archetype]
    except KeyError:
        raise KeyError(f"no pack named '{archetype}' (available: {sorted(PACKS)})") from None
    return build(stacks)
