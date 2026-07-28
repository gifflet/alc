# scaffold.py — Built-in default templates and the scaffolder for `alc init`.
# Writes a conformant Operator Layer (.alc/) into a project root from in-module
# string constants — no package-data configuration required.
from __future__ import annotations

import json
import shutil
from pathlib import Path

from alc.harvest import read_package_scripts

# ---------------------------------------------------------------------------
# Default template constants
# ---------------------------------------------------------------------------

_MANIFEST = """\
version: 1
default_engine: mock

compute_tiers:
  standard:
    mock: "mock-small"
    claude-code: "claude-sonnet-4-6"
  deep:
    mock: "mock-large"
    claude-code: "claude-opus-4-8"

engines:
  mock:
    type: mock
  claude-code:
    type: claude-code
    binary: claude
    # clean_config: true  # skip the host project's .claude/ settings and hooks

# Behavioral knobs — defaults shown; uncomment a line to override:
# default_timeout_s: 1800   # engine per-turn kill timeout (seconds)
# plan_retries: 2           # corrective retries when a plan's JSON is malformed
# fanout_concurrency: 4     # parallel workers for `alc conduct --parallel`
# plan_tier: standard       # compute tier for Conductor planning turns

# Reusable named check sets a Blueprint may opt into via `check_set: <name>`.
# `alc init` pre-filled one set per detected stack plus `security`. A command
# left commented out means its binary was not found on PATH at init time —
# install it and uncomment the check rather than shipping a check that fails
# on a clean checkout.
check_sets:
{check_sets_block}

{worktree_provision_block}blueprints_dir: .alc/blueprints
flows_dir: .alc/flows
queue_dir: .alc/queue
specialists_dir: .alc/specialists
"""

# Placeholder checks block used when no stack is detected.
# The {checks_block} placeholder in chore/bug/feature templates is replaced
# by detect_stack() output or this default at scaffold() time.
_DEFAULT_CHECKS_BLOCK = """\
  # Replace this with your real checks, e.g. ["ruff", "check", "."] and ["pytest", "-q"]
  - name: smoke
    command: ["true"]"""

# A blueprint's inline check whose binary is not on PATH at `alc init` is scaffolded
# COMMENTED OUT for the same reason a check_set entry is — a live check that fails on a
# clean checkout cannot be law — with this hint so the operator knows how to activate it.
_BLUEPRINT_OFF_PATH_HINT = (
    "  # A check whose binary was not on PATH at `alc init` is commented out — a live\n"
    "  # check that fails on a clean checkout cannot be law. Install it (or run\n"
    "  # `alc onboard` to adopt the checks your project already declares), then\n"
    "  # uncomment. Until a real check is live this Blueprint verifies via smoke only."
)


def render_blueprint_checks(checks: list[tuple[str, list[str]]]) -> str:
    """Render a Blueprint's inline `checks:` block, PATH-aware like `render_check_set`.

    Each (name, command) whose binary (``command[0]``) is not on PATH is written
    COMMENTED OUT — a live check that exits 127 on a clean checkout cannot be law, and
    a blueprint that shipped one would fail EVERY run on a machine where the tool lives
    behind a venv/wrapper rather than bare on PATH (e.g. pytest under `uv`). When NO
    check is live the block falls back to the smoke placeholder, so the Blueprint is
    honestly *smoke-only* — the exact shape `alc onboard` opts into a harvested
    `project` check_set. When every check is live the output is byte-identical to the
    pre-PATH-aware hardcoded block (no hint, no smoke fallback), so an on-PATH scaffold
    does not move.

    An empty `checks` (no stack detected) returns the default placeholder block
    unchanged.
    """
    if not checks:
        return _DEFAULT_CHECKS_BLOCK
    lines: list[str] = []
    any_live = False
    any_commented = False
    for name, command in checks:
        if shutil.which(command[0]) is None:
            any_commented = True
            lines.append(f"  # - name: {name}")
            lines.append(f"  #   command: {json.dumps(command)}")
        else:
            any_live = True
            lines.append(f"  - name: {name}")
            lines.append(f"    command: {json.dumps(command)}")
    if not any_live:
        # No detectable check is runnable — fall back to the smoke placeholder so the
        # Blueprint is honestly smoke-only rather than shipping a live check that 127s.
        lines.append("  - name: smoke")
        lines.append('    command: ["true"]')
    if any_commented:
        lines.insert(0, _BLUEPRINT_OFF_PATH_HINT)
    return "\n".join(lines)

_CHORE = """\
---
name: chore
purpose: Apply a low-risk, well-scoped maintenance change.
compute_tier: standard
checks:
{checks_block}
report:
  format: json
  schema:
    status: string
    summary: string
---

## Chore Workflow

1. Read the task description and locate the relevant files.
2. Make the smallest change that satisfies the task; keep it single-purpose.
3. Do not touch files outside the stated scope.
4. Run the checks to verify correctness.
5. Output a JSON report matching the schema:
   ```json
   {{"status": "ok", "summary": "<one sentence describing what was done>"}}
   ```
"""

_BUG = """\
---
name: bug
purpose: Diagnose and fix a bug.
compute_tier: standard
checks:
{checks_block}
report:
  format: json
  schema:
    status: string
    root_cause: string
    fix: string
    summary: string
---

## Bug Workflow

1. Reproduce the bug using the information in the task description.
2. Find the root cause — trace it to the smallest possible location.
3. Apply the smallest fix that resolves the root cause without side effects.
4. Validate the fix by running the checks.
5. Output a JSON report matching the schema:
   ```json
   {{
     "status": "ok",
     "root_cause": "<what caused the bug>",
     "fix": "<what was changed>",
     "summary": "<one sentence summary>"
   }}
   ```
"""

_FEATURE = """\
---
name: feature
purpose: Implement a new feature.
compute_tier: deep
checks:
{checks_block}
report:
  format: json
  schema:
    status: string
    summary: string
---

## Feature Workflow

1. Understand the requirement stated in the task description.
2. Design the smallest viable approach that satisfies the requirement.
3. Implement the feature following the existing code style and conventions.
4. Verify the implementation by running the checks.
5. Output a JSON report matching the schema:
   ```json
   {{"status": "ok", "summary": "<one sentence describing what was implemented>"}}
   ```
"""

# plan.md always keeps the ["true"] smoke check — the planning stage produces no code.
_PLAN = """\
---
name: plan
purpose: Produce a focused implementation plan.
compute_tier: deep
checks:
  # Replace this with your real checks, e.g. ["ruff", "check", "."] and ["pytest", "-q"]
  - name: smoke
    command: ["true"]
report:
  format: json
  schema:
    plan: string
---

## Plan Workflow

1. Read the task description and any relevant files to understand the scope.
2. Produce a concise, numbered step-by-step implementation plan.
3. Each step should be actionable and independently verifiable.
4. Do NOT write application code in this stage — planning only.
5. Output a JSON report matching the schema:
   ```json
   {"plan": "<the full step-by-step plan as text>"}
   ```
"""

_SHIP = """\
name: ship
description: Plan a change, then implement it — each stage its own mandate.
stages:
  - name: plan
    blueprint: plan
  - name: build
    blueprint: feature
"""

# A `.gitignore` INSIDE `.alc/` so the runtime subdirs ALC fills at run time are
# never accidentally tracked: run reports (`runs/`), the task queue (`queue/`), and
# the metric ledger (`metrics/`). The tracked operator layer is the CONFIG —
# manifest.yaml, blueprints/, flows/, specialists/, prompts/. NOTE `metrics/` is
# written to the MAIN operator layer even by an `--isolate` run (the ledger must be
# canonical for the regression gate across isolated runs), so a tracked ledger would
# otherwise dirty the main tree on every isolated metric run.
_GITIGNORE = """\
# The tracked operator layer is CONFIG only; everything else under .alc/ is runtime
# state ALC regenerates (runs/, queue/, metrics/, variants/, and any dir a future
# feature adds). This is an ALLOWLIST: the config is a BOUNDED, known set, so we
# track it and ignore everything else by default — a new runtime dir never needs a
# rule here. (A DENYLIST leaked repeatedly as features added runtime dirs.) Add a
# NEW config file/dir to the allowlist below.
/*
!.gitignore
!manifest.yaml
!blueprints/
!flows/
!loops/
!specialists/
!prompts/
!primers/
# loops/ and specialists/ hold runtime files ALONGSIDE their .yaml config — re-ignore
# those so only the config is tracked.
loops/*.state.json
loops/*.ledger.jsonl
specialists/*.knowledge.md
"""


# ---------------------------------------------------------------------------
# Stack detection
# ---------------------------------------------------------------------------

def detect_stack(project_root: Path) -> tuple[str | None, str]:
    """Detect the project's technology stack from well-known marker files.

    Checks for marker files in project_root in precedence order:
      go.mod -> Go
      pyproject.toml or setup.py -> Python
      package.json -> Node
      Cargo.toml -> Rust
      Gemfile -> Ruby
      composer.json -> PHP
      pom.xml -> Maven
      build.gradle or build.gradle.kts -> Gradle
      mix.exs -> Elixir
      any *.csproj or *.sln -> .NET

    Args:
        project_root: Directory to inspect for marker files.

    Returns:
        A 2-tuple of (stack_label, checks_block) where:
          - stack_label is a short label string (e.g. "Go") or None when
            no known stack was detected.
          - checks_block is a YAML snippet (correctly indented for blueprint
            front-matter) representing the checks for that stack, or the
            default placeholder block when no stack was detected. A check whose
            binary is not on PATH at init time is rendered COMMENTED OUT (with a
            smoke fallback) by render_blueprint_checks — byte-identical to the old
            hardcoded block only when every command is on PATH.
    """
    if (project_root / "go.mod").exists():
        return ("Go", render_blueprint_checks([
            ("build", ["go", "build", "./..."]),
            ("vet", ["go", "vet", "./..."]),
        ]))
    if (project_root / "pyproject.toml").exists() or (project_root / "setup.py").exists():
        return ("Python", render_blueprint_checks([
            ("test", ["pytest", "-q"]),
        ]))
    if (project_root / "package.json").exists():
        return ("Node", render_blueprint_checks([
            ("test", ["npm", "test"]),
        ]))
    if (project_root / "Cargo.toml").exists():
        return ("Rust", render_blueprint_checks([
            ("check", ["cargo", "check"]),
        ]))
    if (project_root / "Gemfile").exists():
        return ("Ruby", render_blueprint_checks([
            ("test", ["bundle", "exec", "rspec"]),
            ("lint", ["bundle", "exec", "rubocop"]),
        ]))
    if (project_root / "composer.json").exists():
        return ("PHP", render_blueprint_checks([
            ("test", ["composer", "test"]),
            ("analyse", ["vendor/bin/phpstan", "analyse"]),
        ]))
    if (project_root / "pom.xml").exists():
        return ("Maven", render_blueprint_checks([
            ("test", ["mvn", "-q", "test"]),
            ("verify", ["mvn", "-q", "verify"]),
        ]))
    if (project_root / "build.gradle").exists() or (project_root / "build.gradle.kts").exists():
        return ("Gradle", render_blueprint_checks([
            ("test", ["./gradlew", "test"]),
            ("check", ["./gradlew", "check"]),
        ]))
    if (project_root / "mix.exs").exists():
        return ("Elixir", render_blueprint_checks([
            ("test", ["mix", "test"]),
            ("credo", ["mix", "credo"]),
        ]))
    if any(project_root.glob("*.csproj")) or any(project_root.glob("*.sln")):
        return (".NET", render_blueprint_checks([
            ("build", ["dotnet", "build"]),
            ("test", ["dotnet", "test"]),
        ]))
    return (None, _DEFAULT_CHECKS_BLOCK)


# Marker file(s) -> (stack label, check_set name, full check battery) in
# precedence order. detect_stacks() below returns EVERY stack that matches
# (unlike detect_stack(), which stops at the first) — a project with both
# pyproject.toml and package.json gets checks for both instead of losing half.
_STACK_DEFS: list[tuple[tuple[str, ...], str, str, list[tuple[str, list[str]]]]] = [
    (
        ("go.mod",),
        "Go",
        "go",
        [
            ("build", ["go", "build", "./..."]),
            ("vet", ["go", "vet", "./..."]),
            ("test", ["go", "test", "./..."]),
        ],
    ),
    (
        ("pyproject.toml", "setup.py"),
        "Python",
        "python",
        [
            ("test", ["pytest", "-q"]),
            ("lint", ["ruff", "check", "."]),
        ],
    ),
    (
        ("package.json",),
        "Node",
        "node",
        [
            ("test", ["npm", "test"]),
            ("lint", ["npm", "run", "lint"]),
            ("typecheck", ["npm", "run", "typecheck"]),
        ],
    ),
    (
        ("Cargo.toml",),
        "Rust",
        "rust",
        [
            ("check", ["cargo", "check"]),
            ("test", ["cargo", "test"]),
            ("clippy", ["cargo", "clippy"]),
        ],
    ),
    (
        ("Gemfile",),
        "Ruby",
        "ruby",
        [
            ("test", ["bundle", "exec", "rspec"]),
            ("lint", ["bundle", "exec", "rubocop"]),
        ],
    ),
    (
        ("composer.json",),
        "PHP",
        "php",
        [
            ("test", ["composer", "test"]),
            ("analyse", ["vendor/bin/phpstan", "analyse"]),
        ],
    ),
    (
        ("pom.xml",),
        "Maven",
        "maven",
        [
            ("test", ["mvn", "-q", "test"]),
            ("verify", ["mvn", "-q", "verify"]),
        ],
    ),
    (
        ("build.gradle", "build.gradle.kts"),
        "Gradle",
        "gradle",
        [
            ("test", ["./gradlew", "test"]),
            ("check", ["./gradlew", "check"]),
        ],
    ),
    (
        ("mix.exs",),
        "Elixir",
        "elixir",
        [
            ("test", ["mix", "test"]),
            ("credo", ["mix", "credo"]),
        ],
    ),
    # The .NET markers are GLOBS (any *.csproj / *.sln file), not exact names —
    # _marker_present() dispatches on the '*' to project_root.glob().
    (
        ("*.csproj", "*.sln"),
        ".NET",
        "dotnet",
        [
            ("build", ["dotnet", "build"]),
            ("test", ["dotnet", "test"]),
        ],
    ),
]

# Stack-specific security scanner, keyed by the stack's check_set name.
_SECURITY_SCANNERS: dict[str, tuple[str, list[str]]] = {
    "go": ("govulncheck", ["govulncheck", "./..."]),
    "python": ("pip-audit", ["pip-audit"]),
    "node": ("npm-audit", ["npm", "audit"]),
    "rust": ("cargo-audit", ["cargo", "audit"]),
    "ruby": ("bundler-audit", ["bundle", "exec", "bundler-audit", "check"]),
    "php": ("composer-audit", ["composer", "audit"]),
}
# Secret scanning is not stack-specific, so it is always part of `security`.
_GITLEAKS_CHECK: tuple[str, list[str]] = ("gitleaks", ["gitleaks", "detect"])


def _marker_present(project_root: Path, marker: str) -> bool:
    """True when *marker* is present in *project_root*.

    A marker containing '*' is a glob (any matching file counts, e.g. a *.csproj);
    every other marker is an exact filename matched with .exists(). KISS: this is
    the only extension needed to support the .NET glob markers alongside the
    exact-name markers every other stack uses.
    """
    if "*" in marker:
        return any(project_root.glob(marker))
    return (project_root / marker).exists()


def detect_stacks(project_root: Path) -> list[tuple[str, str, list[tuple[str, list[str]]]]]:
    """Detect every technology stack present, each with its full check battery.

    Unlike detect_stack() (first-match-wins, a single 2-tuple), this returns ONE
    entry per stack whose marker file(s) exist, so a polyglot project (e.g.
    pyproject.toml + package.json) is not silently reduced to a single stack.

    Args:
        project_root: Directory to inspect for marker files.

    Returns:
        A list of (stack_label, check_set_name, checks) tuples, one per detected
        stack, in marker precedence order (Go, Python, Node, Rust, Ruby, PHP,
        Maven, Gradle, Elixir, .NET). `checks` is the full
        [(check_name, command), ...] battery for that stack.
    """
    return [
        (label, set_name, checks)
        for markers, label, set_name, checks in _STACK_DEFS
        if any(_marker_present(project_root, marker) for marker in markers)
    ]


def _build_check_sets(
    stacks: list[tuple[str, str, list[tuple[str, list[str]]]]],
) -> dict[str, list[tuple[str, list[str]]]]:
    """Build the {check_set_name: checks} mapping for the detected stacks + security.

    One set per detected stack (its full battery), plus a `security` set with
    that stack's scanner (when known) and gitleaks (always, stack-agnostic).
    """
    sets: dict[str, list[tuple[str, list[str]]]] = {}
    security: list[tuple[str, list[str]]] = []
    for _label, set_name, checks in stacks:
        sets[set_name] = checks
        if set_name in _SECURITY_SCANNERS:
            security.append(_SECURITY_SCANNERS[set_name])
    security.append(_GITLEAKS_CHECK)
    sets["security"] = security
    return sets


def render_check_set(
    name: str,
    checks: list[tuple[str, list[str]]],
    unavailable: frozenset[str] | set[str] | tuple[str, ...] = (),
) -> str:
    """Render one named check_sets entry as a manifest.yaml YAML block.

    A check whose binary is not found on PATH is written commented out — a
    live check that fails on a clean checkout would break every run. A set
    left with zero live checks still renders as an explicit empty list so the
    Manifest still parses.

    `unavailable` names checks to comment out for a reason PATH cannot see — e.g.
    a Node `npm run <script>` whose script is absent from package.json (it would
    error "Missing script"). They render identically to an off-PATH binary, so the
    operator uncomments them once the underlying script/binary exists.

    Public so other modules (e.g. `alc.onboard`) can reuse the exact
    off-PATH commenting logic when rendering a proposed check_sets block.
    """
    unavailable = set(unavailable)
    lines = [f"  {name}:"]
    any_live = False
    for check_name, command in checks:
        commented = shutil.which(command[0]) is None or check_name in unavailable
        prefix = "# " if commented else ""
        lines.append(f"    {prefix}- name: {check_name}")
        lines.append(f"    {prefix}  command: {json.dumps(command)}")
        any_live = any_live or not commented
    if not any_live:
        lines.insert(1, "    []")
    return "\n".join(lines)


# Backwards-compatible private alias — `render_check_set` was `_render_check_set`
# before it was promoted for reuse; keep the old name so nothing that imported it
# breaks.
_render_check_set = render_check_set


# Node's typecheck script has no canonical name — projects spell it several ways.
# Resolve to the first spelling that actually EXISTS so the scaffolded
# `npm run <script>` cannot fail with "Missing script"; priority order fixes the
# winner when a project (unusually) declares more than one.
_NODE_TYPECHECK_VARIANTS: tuple[str, ...] = ("typecheck", "type-check", "type:check")


def _resolve_node_checks(
    checks: list[tuple[str, list[str]]], scripts: dict[str, str]
) -> tuple[list[tuple[str, list[str]]], set[str]]:
    """Rewrite the static Node battery against the project's REAL package.json scripts.

    `npm test` / `npm run <script>` errors "Missing script" when the script is
    absent, so scaffolding it live would fail EVERY run — it cannot be law. Returns
    the battery with each command bound to the script that actually exists (and
    `typecheck` mapped to whichever of its spellings is present), plus the set of
    check NAMES whose script is absent so the caller comments them out. The check
    NAMES stay stable (`test`/`lint`/`typecheck`) so downstream references never
    churn even when the underlying script is spelled differently.
    """
    resolved: list[tuple[str, list[str]]] = []
    unavailable: set[str] = set()
    for check_name, command in checks:
        if check_name == "typecheck":
            variant = next((v for v in _NODE_TYPECHECK_VARIANTS if v in scripts), None)
            if variant is None:
                resolved.append((check_name, command))
                unavailable.add(check_name)
            else:
                resolved.append((check_name, ["npm", "run", variant]))
        else:
            # `test`/`lint` invoke a script of the same name — keep the command,
            # but comment the check out when that script is not declared.
            resolved.append((check_name, command))
            if check_name not in scripts:
                unavailable.add(check_name)
    return resolved, unavailable


def _render_check_sets_block(
    stacks: list[tuple[str, str, list[tuple[str, list[str]]]]], project_root: Path
) -> str:
    """Render the full `check_sets:` mapping body for detected stacks + security.

    The `node` set is resolved against the project's real package.json scripts so
    an absent-script check is scaffolded commented out rather than live-and-broken.
    """
    check_sets = _build_check_sets(stacks)
    blocks: list[str] = []
    for name, checks in check_sets.items():
        if name == "node":
            resolved, unavailable = _resolve_node_checks(
                checks, read_package_scripts(project_root)
            )
            blocks.append(render_check_set(name, resolved, unavailable=unavailable))
        else:
            blocks.append(render_check_set(name, checks))
    return "\n\n".join(blocks)


# Per-stack gitignored dependency to auto-provision into every isolated worktree,
# plus the ecosystem install that keeps it fresh across a dependency bump. Only
# Node's node_modules is the confirmed near-universal always-gitignored dep dir — a
# git worktree checks out only tracked files, so without a provision a Node check
# (tsc/eslint/vitest) exits 127. Other stacks have no single such directory to link
# in by default, so `alc init` scaffolds a live provision only for the stacks listed
# here (keyed by check_set name). `refresh`/`when_changed` close the deps-bump false
# green — see `_render_worktree_provision_block`.
_STACK_PROVISIONS: dict[str, dict] = {
    "node": {
        "path": "node_modules",
        "refresh": ["npm", "install"],
        "when_changed": ["package.json", "package-lock.json"],
    },
}

# Alternative Node package managers, keyed by the lockfile that proves the project
# uses one. `alc init` sniffs the project root; when a lockfile is present it swaps
# npm's install command AND its lockfile trigger for the real tool, so the isolated
# reinstall matches how the project actually installs. Absent -> npm (the default).
_NODE_MANAGERS: dict[str, tuple[list[str], str]] = {
    "pnpm-lock.yaml": (["pnpm", "install"], "pnpm-lock.yaml"),
    "yarn.lock": (["yarn", "install"], "yarn.lock"),
}


def _render_worktree_provision_block(
    stacks: list[tuple[str, str, list[tuple[str, list[str]]]]],
    project_root: Path | None = None,
) -> str:
    """Render a `worktree_provision:` block for each detected stack's gitignored dep
    dir, or "" when no detected stack has one.

    Each entry links the dep dir into every isolated worktree AND declares a
    `refresh` (the ecosystem install) fired by `when_changed` (the dependency
    manifests). That pair closes the deps-bump false green: when a run edits a
    dependency manifest, ALC reinstalls in an ISOLATED deps dir BEFORE the checks,
    so type-check/build/test see the NEW versions — not the stale symlinked
    node_modules a bare `link:` would otherwise leave in place (a breaking major
    bump would pass green against the already-installed old packages).

    An empty result is byte-identical to before this block existed (the manifest
    simply carries no worktree_provision key). A trailing blank line separates the
    block from the `blueprints_dir` line that follows in the template.
    """
    entries = [
        (set_name, _STACK_PROVISIONS[set_name])
        for _label, set_name, _checks in stacks
        if set_name in _STACK_PROVISIONS
    ]
    if not entries:
        return ""
    lines = [
        "# Gitignored runtime deps symlinked into each isolated worktree before a run.",
        "# A git worktree checks out only tracked files, so these dirs would be absent",
        "# and a check like tsc/eslint/vitest would exit 127 — link them in.",
        "#",
        "# `refresh` + `when_changed` close the deps-bump false green: when a run edits a",
        "# dependency manifest, ALC runs the install in an ISOLATED deps dir BEFORE the",
        "# checks, so type-check/build/test see the NEW versions — not the stale linked",
        "# node_modules (against which a breaking major bump would pass green).",
        "worktree_provision:",
    ]
    for set_name, entry in entries:
        refresh = list(entry["refresh"])
        when_changed = list(entry["when_changed"])
        if set_name == "node" and project_root is not None:
            for lockfile, (cmd, lock) in _NODE_MANAGERS.items():
                if (project_root / lockfile).exists():
                    refresh = cmd
                    when_changed = ["package.json", lock]
                    break
        lines.append(f"  - link: {entry['path']}")
        lines.append(f"    refresh: [{', '.join(refresh)}]")
        lines.append(f"    when_changed: [{', '.join(when_changed)}]")
    return "\n".join(lines) + "\n\n"


# ---------------------------------------------------------------------------
# Scaffolder
# ---------------------------------------------------------------------------

def scaffold(project_root: Path, force: bool = False) -> list[str]:
    """Write the default Operator Layer into project_root/.alc/.

    Creates the full directory structure and all default template files from
    the built-in constants. The generated layer is conformant with the Policy
    Gate (alc lint passes with no error-level violations).

    The chore, bug, and feature blueprints receive real stack-specific checks
    when detect_stack() identifies the project stack AND the check's binary is on
    PATH; a detected check whose binary is absent is scaffolded commented-out with
    a smoke fallback (so the blueprint is honestly smoke-only), and a project with
    no detected stack keeps the placeholder comment + smoke check.  plan.md always
    keeps the ["true"] smoke check because the planning stage produces no code.

    manifest.yaml's `check_sets` gets one named set per stack detect_stacks()
    finds (fuller batteries than the single-stack path above) plus a `security`
    set; neither is referenced by the default blueprints — they exist for
    Blueprints that opt in via `check_set: <name>`.

    Args:
        project_root: The project directory to initialise. .alc/ is created
            as a direct child of this directory.
        force: If True, overwrite an existing .alc/ directory. If False and
            .alc/ already exists, raise FileExistsError.

    Returns:
        Sorted list of created file paths relative to project_root
        (e.g. [".alc/blueprints/bug.md", ".alc/manifest.yaml", ...]).

    Raises:
        FileExistsError: If .alc/ already exists and force is False.
    """
    alc_dir = project_root / ".alc"

    if alc_dir.exists() and not force:
        raise FileExistsError(
            "`.alc/` already exists; pass --force to overwrite"
        )

    # Detect the project stack to provide real checks. The single-stack path
    # (detect_stack) stays first-match-wins; its inline checks are byte-identical
    # to before WHEN THE BINARY IS ON PATH, and are scaffolded commented-out (with
    # a smoke fallback) when it is not — so a run never 127s on a clean checkout and
    # `alc onboard` can opt the now-smoke-only blueprint into a harvested set.
    # detect_stacks() separately feeds the multi-stack check_sets below.
    _stack_label, checks_block = detect_stack(project_root)
    stacks = detect_stacks(project_root)
    check_sets_block = _render_check_sets_block(stacks, project_root)
    # Node's node_modules is gitignored, so a fresh worktree lacks it — scaffold a
    # live `worktree_provision` for it (and any future stack with a known dep dir)
    # so the default setup does not 127. Empty for stacks without one.
    worktree_provision_block = _render_worktree_provision_block(stacks, project_root)

    # Create directory structure.
    (alc_dir / "blueprints").mkdir(parents=True, exist_ok=True)
    (alc_dir / "flows").mkdir(parents=True, exist_ok=True)
    # Empty keyed prompt-override store — reserved prompts resolve to their
    # embedded defaults until an operator ejects/authors a file here.
    (alc_dir / "prompts").mkdir(parents=True, exist_ok=True)

    # Map each relative path to its content.
    files: dict[str, str] = {
        ".alc/manifest.yaml": _MANIFEST.format(
            check_sets_block=check_sets_block,
            worktree_provision_block=worktree_provision_block,
        ),
        ".alc/blueprints/chore.md": _CHORE.format(checks_block=checks_block),
        ".alc/blueprints/bug.md": _BUG.format(checks_block=checks_block),
        ".alc/blueprints/feature.md": _FEATURE.format(checks_block=checks_block),
        ".alc/blueprints/plan.md": _PLAN,
        ".alc/flows/ship.yaml": _SHIP,
        ".alc/.gitignore": _GITIGNORE,
    }

    for rel_path, content in files.items():
        (project_root / rel_path).write_text(content)

    return sorted(files.keys())
