# setup_skill.py — Install or update the user-level Claude Code skill for the alc CLI.
# Writes ~/.claude/skills/alc/SKILL.md so an in-editor Claude agent knows how to drive
# the alc CLI surface.  Project-agnostic; version-stamped; idempotent.
from __future__ import annotations

from pathlib import Path

try:
    from importlib.metadata import version as _pkg_version, PackageNotFoundError
except ImportError:  # Python < 3.8 shim (should never occur for us)
    PackageNotFoundError = Exception  # type: ignore[misc,assignment]
    def _pkg_version(_name: str) -> str:  # type: ignore[misc]
        raise PackageNotFoundError(_name)


# ---------------------------------------------------------------------------
# Version resolution
# ---------------------------------------------------------------------------

def _resolve_version() -> str:
    """Return the installed distribution version, or '0.0.0' as fallback.

    The DISTRIBUTION name is `alc-runtime` (the bare `alc` was too similar to an
    existing PyPI project); the import package and the CLI command stay `alc`.
    """
    try:
        return _pkg_version("alc-runtime")
    except Exception:
        return "0.0.0"


# ---------------------------------------------------------------------------
# SKILL.md template
# ---------------------------------------------------------------------------

SKILL_BODY_TEMPLATE: str = """\
---
name: alc
description: >
  Use when working in a repository that contains a `.alc/` directory (the ALC
  Operator Layer). Drive the `alc` CLI to do verified, control-plane-enforced
  work — run, flow, conduct, explore/compare/adopt, cycle, tick, land — instead
  of editing files directly whenever the task fits a Blueprint or Flow, and to
  read project health with status, audit, team status, and metrics.
---

## What ALC is

ALC is a control plane that lives OUTSIDE the model. You supply the task; ALC
composes the directive, runs the engine, then enforces the project's declared
laws. The Assurance Loop (Act -> Verify -> Repair) runs the checks and repairs
on failure; the Policy Gate blocks disallowed edits; the Scorecard records span,
passes, streak, and touch, plus net-lines. A run can take optional git-worktree
isolation, where edits land on a temporary `alc/*` branch instead of your
working tree. A run reports success only when the checks pass — that is why
routed work is trustworthy and hand-edits are not.

## First: discover this project

Never assume a Blueprint or Flow exists — discover it first.

- `alc status` — pending tasks, outstanding failures, loop states, and unmerged
  `alc/*` branches, at a glance.
- `alc lint` — validate the Operator Layer against the Policy Gate before you
  drive it.
- Read `.alc/manifest.yaml` — the default engine, the `check_sets`, the product
  `stage`, and delivery config.
- List `.alc/blueprints/`, `.alc/flows/`, `.alc/specialists/`, and
  `.alc/loops/` — the units this project actually ships.
- `alc team status` — who is hired and the Mix Health for the declared stage.

These views are cheap and read-only; they tell you what this specific project
can do.

## The command surface, by intent

**Run one verified unit.** `alc run <blueprint> "<task>" [--isolate]
[--engine NAME]` runs a single Blueprint under the Assurance Loop — its checks
run and repair on failure. `alc spike "<task>"` is sugar for the throwaway spike
Blueprint: forced isolation, no checks gate, never merged — use it for a quick
answer.

**Run a pipeline.** `alc flow <flow> "<task>" [--isolate]` runs a multi-stage
Flow; under `--isolate` every stage shares one worktree, so the plan -> build
hand-off survives.

**From a goal, let ALC plan.** `alc conduct "<goal>"` has the Conductor plan the
required Flows and run them now; `--enqueue` writes them to the queue for
`alc tick` instead; `--strict-stage` refuses a plan whose archetypes fall
outside the stage's target mix.

**A specialist over its knowledge.** `alc specialist <name> "<task>"` runs
Recall -> Act -> Learn, accumulating into the specialist's Knowledge File.

**Explore alternatives.** `alc explore <blueprint> "<task>" --variants N` runs N
isolated variants that are NEVER auto-merged (repeat `--engine`/`--tier` to
cross engines and tiers). `alc compare` bare lists every variant; `--diff`
prints each one's diff. `alc adopt <branch>` integrates the winner and discards
its unmerged siblings; already-adopted or deleted variants stay listed as
resolved.

**Work autonomously.** `alc cycle <loop>` runs ONE replenish -> drain -> stop
cycle and exits; `alc loop <loop>` repeats cycles in the foreground until a
backstop (`stop.max_cycles`, `stop.budget`) fires.

**Queue and drain.** `alc enqueue <flow> "<task>"` writes a queue task, isolated
by default; `--touches <path>` serializes overlapping edits, `--id`/
`--depends-on` order dependents, `--from-file` batches. `alc tick` drains the
queue once and exits (`--engine` overrides every demand's engine for that
drain). `alc retry` re-enqueues a failure with its feedback attached, so the
next drain fixes the exact reason.

**Integrate.** `alc land` bare lists the unmerged `alc/*` branches; name a
`<branch>`, or pass `--all`, and add `--push` or `--pr` to deliver. `alc discard`
force-deletes losing branches and prunes stale worktrees.

**Read state.** `alc status`, `alc audit` (bare = the trailing 7 days),
`alc checks` (bare = the audit view; `history` = the flake radar), `alc team`
(bare = status + Mix Health), `alc metrics`, `alc runs list|show|tail`, and
`alc artifacts` (a run's captured e2e evidence).

## The team is the strategy

An Archetype Pack ships the blueprints, flows, and loops for one KIND of work;
`alc team hire <archetype>` installs them. The five:

- **prototyper** — cheap throwaway exploration (the spike Blueprint,
  `alc explore`); losers are discarded, never polished.
- **builder** — real features driven to done (a ship-hardened flow:
  plan -> build -> test -> verify gate), landed or opened as a PR.
- **grower** — improve what exists without regressing; metric checks are its law.
- **sweeper** — simplify and DELETE (a refactor Blueprint expects the diff to
  shrink; a sweep loop finds its own removal work); negative net-lines is a win.
- **maintainer** — keep it green: dependency bumps (a deps-refresh loop, one
  package per demand), a security patrol, and flaky checks.

`alc team hire` is ADDITIVE — it writes only the pack's MISSING files and keeps
yours (`--force` overwrites all); `alc team retire` archives reversibly. The
right mix depends on `stage` in the manifest (pre-pmf / growth / strong-pmf).
Read Mix Health in `alc team status`: it scores real spend per archetype against
the stage's target mix and hints what to do about an idle core archetype — run
its loop, route a demand, or hire it.

## Checks are the law

The checks gate is what makes delegation safe: a run reports success only when
the declared checks pass. NEVER weaken the law to go green — do not loosen a
lint config, rewrite a test script, or touch a check-defining file to slip past
it. ALC treats edits to check configuration (the `check-config-integrity` guard)
and to any `protect:`ed path as failed checks; revert the config and fix the
code instead. A metric check — a command that prints one number, plus a
direction and a tolerance — turns "do not regress" into law: the run fails when
the number regresses against the last accepted measurement, and the series shows
in `alc metrics` (the grower's grow Blueprint ships a commented example). When a
run edits a dependency manifest, ALC reinstalls dependencies before the checks
(env-refresh) — so never instruct a task to run the package manager itself.

## Working autonomously

A Loop cycle replenishes its own work — from a plan, a specialist, pending
signals, or a metric regression — then drains that queue under the law, then
stops at a backstop. `stop.max_cycles` and `stop.budget` are the backstops; a
cycle that is already running always finishes. Prefer a clean working tree
before `alc tick`, `alc cycle`, or `alc loop`: they warn and proceed, never
committing your uncommitted work, and isolated demands (the enqueue default) are
the safe path on a dirty tree. `alc cycle <name> --status` reads loop state
without running; `--reset` restarts a stopped or exhausted loop.

## How to work

- Prefer `alc run` / `alc flow` over hand-editing whenever a Blueprint fits;
  reserve direct edits for what no unit covers.
- Prefer `--isolate` for anything you want to review before it touches the tree;
  review with `alc land` and integrate deliberately.
- Prototype cheaply: `alc spike` for one throwaway answer, `alc explore` for
  competing variants — throw the losers away (`alc adopt` discards the siblings).
  Never polish a prototype into production; rebuild it through a real Blueprint.
- Reward deletion: route cleanup through the sweeper's units; negative net-lines
  is a success signal.
- Never let a number regress silently: put a metric check on anything worth
  protecting and watch `alc metrics`.
- Never weaken a check, a test, or a check-defining config to make a run pass.
  If the law itself is wrong, change it as its own deliberate, reviewed change.
- Keep scope to the task: one demand = one concern; batch related work as
  separate enqueued demands with `--touches`/`--depends-on`, not one mega-task.
- Read before acting: bare `alc status`, `alc audit`, `alc checks`, and
  `alc team` are cheap read views — start there, not with a run.
- Keep effort on the stage's core archetypes; when Mix Health flags off-mix
  spend or an idle core archetype, follow its hint.
- Verify end to end: checks are the evidence; for service-facing work,
  `alc artifacts` shows the live proof.

Generated by alc setup for alc {version}.
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_skill(version: str) -> str:
    """Return the full SKILL.md text with the given version stamp."""
    return SKILL_BODY_TEMPLATE.format(version=version)


# User-level agent-skill directory per engine. Both Claude Code and Gemini CLI
# use the same SKILL.md format; only the install location differs.
_SKILLS_DIRS: dict[str, tuple[str, ...]] = {
    "claude-code": (".claude", "skills"),
    "gemini": (".gemini", "skills"),
}


def supported_engines() -> list[str]:
    """Return the engines that have a user-level editor skill integration."""
    return sorted(_SKILLS_DIRS)


def install_skill(
    engine: str = "claude-code",
    skills_root: Path | None = None,
    version: str | None = None,
) -> tuple[Path, bool]:
    """Write the ALC skill to skills_root/alc/SKILL.md.

    Args:
        engine: Which engine's editor to install for. Selects the user-level
            skills directory (claude-code -> ~/.claude/skills,
            gemini -> ~/.gemini/skills). Ignored when ``skills_root`` is given.
        skills_root: Parent directory for skill namespaces. When omitted, it is
            resolved from ``engine``.
        version: Version string to embed in the skill. Defaults to the installed
            distribution version (``importlib.metadata``).

    Returns:
        A ``(path, changed)`` tuple where *path* is the target file and
        *changed* is ``True`` when the file was written (created or updated)
        or ``False`` when the existing content was already identical.

    Raises:
        ValueError: If ``skills_root`` is omitted and ``engine`` has no known
            editor skill integration (e.g. the mock engine).
    """
    if skills_root is None:
        if engine not in _SKILLS_DIRS:
            raise ValueError(
                f"no editor skill integration for engine '{engine}'; "
                f"supported: {supported_engines()}"
            )
        skills_root = Path.home().joinpath(*_SKILLS_DIRS[engine])
    if version is None:
        version = _resolve_version()

    target = skills_root / "alc" / "SKILL.md"
    content = render_skill(version)

    if target.exists() and target.read_text() == content:
        return target, False

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return target, True
