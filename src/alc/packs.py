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


# ---------------------------------------------------------------------------
# Sweeper pack — a dead-code detector, a behavior-preserving refactor
# Blueprint, and the unship flow that removes what the janitor finds.
# ---------------------------------------------------------------------------

_SWEEPER_REFACTOR = """\
---
name: refactor
purpose: Simplify the code behavior-preservingly — remove dead or unused surface.
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
archetype: sweeper
---

## Refactor Workflow

1. Find dead or unused code with the stack's real detector: `vulture .`
   (Python), `knip` or `ts-prune` (Node), `staticcheck -unused ./...` (Go), or
   `cargo-udeps` (Rust) — whichever matches this project.
2. Simplify or remove ONE finding (the one named in the task, when given)
   without changing observable behavior — no new features, no API changes.
3. Run the checks — including the stack's full check_set, when declared — to
   confirm nothing broke.
4. Output a JSON report matching the schema:
   ```json
   {{"status": "ok", "summary": "<one sentence describing what was simplified or removed>"}}
   ```
"""

_SWEEPER_JANITOR = """\
name: janitor
area: dead and unused code across the codebase — the accumulated cruft map
blueprint: refactor
knowledge_path: .alc/specialists/janitor.knowledge.md
"""

_SWEEPER_SWEEP_LOOP = """\
name: sweep
replenish:
  kind: plan
  ref: janitor
  task: >
    Find dead or unused code across the repository. For every finding, emit
    one plan item targeting the `unship` flow, with "touches" set to the
    file(s) it will edit so overlapping findings serialize instead of racing.
stop:
  max_cycles: 10
"""

_SWEEPER_UNSHIP_FLOW = """\
name: unship
description: Map what a finding touches, remove it behavior-preservingly, then a pure gate.
stages:
  - name: map
    blueprint: plan
  - name: remove
    blueprint: refactor
  - name: gate
    blueprint: refactor
    verify_only: true
"""


def _sweeper_files(
    stacks: list[tuple[str, str, list[tuple[str, list[str]]]]],
) -> dict[str, str]:
    """Build the Sweeper pack: the janitor Specialist, a refactor Blueprint, its
    sweep Loop, and the unship Flow it enqueues one demand per finding into."""
    return {
        ".alc/blueprints/refactor.md": _SWEEPER_REFACTOR.format(
            check_set_line=_check_set_line(stacks)
        ),
        ".alc/specialists/janitor.yaml": _SWEEPER_JANITOR,
        ".alc/loops/sweep.yaml": _SWEEPER_SWEEP_LOOP,
        ".alc/flows/unship.yaml": _SWEEPER_UNSHIP_FLOW,
    }


# ---------------------------------------------------------------------------
# Maintainer pack — a security patrol, a chore-per-package dependency
# refresh Loop, and the plumbing (a scan gate, a bare chore Flow) they need.
# ---------------------------------------------------------------------------

_MAINTAINER_SCAN = """\
---
name: scan
purpose: Verify the codebase against the security check_set as a pure gate.
compute_tier: standard
check_set: security
checks:
  # `security` (T5) can render empty when no scanner binary was on PATH at
  # `alc init` time — a pack Blueprint must never depend on a check_set alone.
  # This inline check keeps the gate lint-clean and non-empty regardless.
  - name: smoke
    command: ["true"]
report:
  format: json
  schema:
    status: string
    summary: string
archetype: maintainer
---

## Scan Workflow

This Blueprint only ever runs `verify_only` (see `flows/patrol.yaml`): its
checks — the `security` check_set plus the smoke check above — run as a pure
gate, with no engine turn.
"""

_MAINTAINER_PATROL_FLOW = """\
name: patrol
description: Scan for security issues as a pure gate, then apply a routine maintenance fix.
stages:
  - name: scan
    blueprint: scan
    verify_only: true
  - name: fix
    blueprint: chore
"""

# A bare one-stage wrapper around the default `chore` Blueprint, so a single
# outdated package can be dispatched as its own isolated queue unit (`alc
# enqueue` writes a "flow" or "specialist" task — never a bare Blueprint).
_MAINTAINER_CHORE_FLOW = """\
name: chore
description: One isolated chore, dispatched as its own queue unit (e.g. via `alc enqueue`).
stages:
  - name: apply
    blueprint: chore
"""

_MAINTAINER_DEPS = """\
name: deps
area: dependency versions across the project's package manifest(s) — what has already been tried per package
blueprint: chore
knowledge_path: .alc/specialists/deps.knowledge.md
"""

_MAINTAINER_DEPS_REFRESH_LOOP = """\
name: deps-refresh
replenish:
  kind: specialist
  ref: deps
  task: >
    Check for outdated dependencies with the stack's real command (`pip list
    --outdated` for Python, `npm outdated` for Node, `go list -m -u all` for
    Go, `cargo outdated` for Rust). For every outdated package, enqueue ONE
    isolated chore via `alc enqueue chore "<task>" --touches <manifest
    file>` — never batch several packages into one demand. Give a demand
    `--id <slug>` when a later one bumps a related major (e.g. a framework
    and its official plugin) so the dependent one can `--depends-on <slug>`
    and land in the right order instead of racing.
stop:
  max_cycles: 10
"""


# ---------------------------------------------------------------------------
# Grower pack — DELIBERATELY PARTIAL (roadmap-phase-2.md T12). The Grower's
# loop is hypothesis -> change -> measurement; this wave ships only a DIY
# signal-gathering Specialist. Real signal intake (issue trackers, APM, crash
# reports), metric checks, and the `regression` replenish kind are Phases 4-5.
# ---------------------------------------------------------------------------

_GROWER_LISTEN = """\
# listen — a DIY sweep of user-reported issues and error reports. ALC does
# NOT ingest signal automatically yet: the operator feeds this Specialist raw
# reports as the task text on each invocation (e.g. `alc specialist listen
# "<pasted issue reports>"`), and its Knowledge File accumulates what users
# keep hitting over time. This pack is DELIBERATELY PARTIAL — automated
# signal intake, metric checks, and the `regression` replenish kind land in
# Phases 4-5 (see docs/roadmap-phase-2.md).
name: listen
area: user-reported issues and error reports — a durable map of what users keep hitting
blueprint: plan
knowledge_path: .alc/specialists/listen.knowledge.md
"""


def _grower_files(
    stacks: list[tuple[str, str, list[tuple[str, list[str]]]]],
) -> dict[str, str]:
    """Build the Grower pack: a DIY issue/error-sweep Specialist only.

    `stacks` is unused — the sweep is DIY (operator-fed), not stack-specific;
    kept for signature parity with the other packs in PACKS. `listen` reuses
    the default `plan` Blueprint (read/synthesize, no code changes) rather
    than shipping its own — this wave adds no new Blueprint for Grower.
    """
    return {".alc/specialists/listen.yaml": _GROWER_LISTEN}


def _maintainer_files(
    stacks: list[tuple[str, str, list[tuple[str, list[str]]]]],
) -> dict[str, str]:
    """Build the Maintainer pack: a security patrol Flow, a bare chore Flow, the
    deps Specialist, and the Loop that refreshes one package at a time.

    `stacks` is unused — every file this pack writes is stack-agnostic (the
    `security` check_set and the `chore` Blueprint are both named, not stack-
    specific); kept for signature parity with the other packs in PACKS.
    """
    return {
        ".alc/blueprints/scan.md": _MAINTAINER_SCAN,
        ".alc/flows/patrol.yaml": _MAINTAINER_PATROL_FLOW,
        ".alc/flows/chore.yaml": _MAINTAINER_CHORE_FLOW,
        ".alc/specialists/deps.yaml": _MAINTAINER_DEPS,
        ".alc/loops/deps-refresh.yaml": _MAINTAINER_DEPS_REFRESH_LOOP,
    }


# Archetype name -> file-generator. `grower` ships PARTIAL (see _grower_files);
# `prototyper` is a later wave and simply absent from this table until it lands
# — `alc team hire` reports that plainly (see pack_files' KeyError) instead of
# failing.
PACKS: dict[
    str, Callable[[list[tuple[str, str, list[tuple[str, list[str]]]]]], dict[str, str]]
] = {
    "builder": _builder_files,
    "sweeper": _sweeper_files,
    "maintainer": _maintainer_files,
    "grower": _grower_files,
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
