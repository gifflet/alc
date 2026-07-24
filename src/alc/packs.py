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
# e2e evidence (roadmap-phase-5.md T6): runs once the health poll has already
# proven the service reachable, and writes into $ALC_ARTIFACTS_DIR — ALC
# collects whatever lands there (plus the health-poll log) into the
# RunReport, readable back via `alc artifacts`. Swap for a real screenshot
# tool; this curl is the smallest example that proves the pattern.
capture: curl -sf "$ALC_BASE_URL" -o "$ALC_ARTIFACTS_DIR/health-check.txt"
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
protect: ["tests/**", "test/**"]
expect: shrink
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

_SWEEPER_MAP = """\
---
name: map
purpose: Map the public symbols a feature exposes, for `unship`'s optional derive_checks gate.
compute_tier: standard
checks:
  # This stage only maps a surface — it changes nothing, so a smoke check is enough.
  - name: smoke
    command: ["true"]
report:
  format: json
  schema:
    symbols: list
    summary: string
---

## Map Workflow

This stage is used ONLY when you enable the optional map + derive_checks stages
in `unship` (a grep-based prove-absence opt-in). The default `unship` gate
verifies the removal with the project's real checks instead, so an ordinary
removal never runs this stage.

1. Read the task description to identify the feature being removed.
2. List ONLY the UNIQUE identifiers that feature exposes as its public surface —
   function, class, endpoint, CLI flag, or config key names that another part of
   the codebase, or a user, references by that exact name. The `gate` stage
   proves absence by searching the repo for each name literally, so a name that
   is not unique cannot be proven absent: do NOT list generic tokens (common CSS
   properties like `font-size`, language keywords, or substrings that appear
   widely across the codebase).
3. If the removal has no such unique symbol — a redundant or duplicate
   declaration, a generic property, dead styling — return an EMPTY list. That is
   correct: the `gate` then reports the removal as inconclusive (nothing to
   prove) instead of failing on a name that cannot be proven absent.
4. Do NOT change any code in this stage — mapping only; `remove` does the edit.
5. Output a JSON report matching the schema:
   ```json
   {"symbols": ["<unique_symbol>", ...], "summary": "<one sentence>"}
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
description: Remove a feature behavior-preservingly, then verify the removal with the project's real checks.
stages:
  - name: remove
    blueprint: refactor
  - name: gate
    blueprint: refactor
    verify_only: true
    require_real_checks: true
# ---------------------------------------------------------------------------
# OPT-IN: prove-absence by text search (map + derive_checks).
#
# The gate above verifies the removal with the project's REAL checks (checks
# are law). Text search is only a heuristic — a name that is not unique can
# never be proven absent — so real checks are preferred. To ALSO grep the repo
# for every removed symbol, add a `map` stage BEFORE `remove` and give the gate
# a `derive_checks` block instead of `require_real_checks`:
#
#   - name: map
#     blueprint: map
#   - name: remove
#     blueprint: refactor
#   - name: gate
#     blueprint: refactor
#     verify_only: true
#     derive_checks:
#       from_stage: map
#       field: symbols
#       shell_template: '! grep -rn {value} . --exclude-dir=.git --exclude-dir=.alc --exclude-dir=node_modules'
#
# The `map` stage lists only UNIQUE symbols and returns an EMPTY list when the
# removal has none (routing the gate to inconclusive). See .alc/blueprints/map.md.
# ---------------------------------------------------------------------------
"""


def _sweeper_files(
    stacks: list[tuple[str, str, list[tuple[str, list[str]]]]],
) -> dict[str, str]:
    """Build the Sweeper pack: a refactor Blueprint, the janitor Specialist, its
    sweep Loop, and the unship Flow — remove -> a require_real_checks gate that
    verifies the removal with the project's REAL checks (checks are law), reporting
    INCONCLUSIVE when the project has only placeholder checks. The grep-based
    prove-absence strategy (a map Blueprint + a derive_checks gate,
    roadmap-phase-4.md T9) is retained as a documented opt-in: map.md still ships
    and the unship Flow carries the recipe as a commented block."""
    return {
        ".alc/blueprints/map.md": _SWEEPER_MAP,
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


# ---------------------------------------------------------------------------
# Prototyper pack — a single throwaway `spike` Blueprint. `mode: spike` is the
# ONE relaxation of the checks gate (roadmap-phase-3.md T1): it declares no
# checks at all, and the Policy Gate downgrades that from error to warn only
# in this mode. The control plane fences the rest (forced isolation, zero
# repairs, no commit/auto-merge) — see runner.py and cli.py.
# ---------------------------------------------------------------------------

_PROTOTYPER_SPIKE = """\
---
name: spike
purpose: Explore a technical question fast — throwaway code, no delivery guarantee.
compute_tier: standard
mode: spike
report:
  format: json
  schema:
    status: string
    summary: string
archetype: prototyper
---

## Spike Workflow

1. Read the task as a question to answer or a hypothesis to test — not a feature to ship.
2. Write the smallest throwaway code that answers it. Skip tests, polish, and edge
   cases; this code is never merged.
3. Summarize what you learned: does the approach work, what did it cost, what would a
   real implementation need to handle that this spike skipped.
4. Output a JSON report matching the schema:
   ```json
   {{"status": "ok", "summary": "<one sentence describing what the spike learned>"}}
   ```

This Blueprint declares `mode: spike`: the Policy Gate does not require checks here
(rule 1 drops to a warn), and the control plane forces isolation, zero repair turns,
and never commits or auto-merges what it wrote — a spike is disposable by construction.
"""


def _prototyper_files(
    stacks: list[tuple[str, str, list[tuple[str, list[str]]]]],
) -> dict[str, str]:
    """Build the Prototyper pack: a single throwaway `spike` Blueprint.

    `stacks` is unused — `mode: spike` skips checks by design (Policy Gate rule
    1 drops to a warn in that mode), so there is no stack-specific check_set to
    reference; kept for signature parity with the other packs in PACKS.
    """
    return {".alc/blueprints/spike.md": _PROTOTYPER_SPIKE}


# Archetype name -> file-generator. `grower` ships PARTIAL (see _grower_files).
PACKS: dict[
    str, Callable[[list[tuple[str, str, list[tuple[str, list[str]]]]]], dict[str, str]]
] = {
    "builder": _builder_files,
    "sweeper": _sweeper_files,
    "maintainer": _maintainer_files,
    "grower": _grower_files,
    "prototyper": _prototyper_files,
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
