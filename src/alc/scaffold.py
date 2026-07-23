# scaffold.py — Built-in default templates and the scaffolder for `alc init`.
# Writes a conformant Operator Layer (.alc/) into a project root from in-module
# string constants — no package-data configuration required.
from __future__ import annotations

import json
import shutil
from pathlib import Path

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

blueprints_dir: .alc/blueprints
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

    Args:
        project_root: Directory to inspect for marker files.

    Returns:
        A 2-tuple of (stack_label, checks_block) where:
          - stack_label is a short label string (e.g. "Go") or None when
            no known stack was detected.
          - checks_block is a YAML snippet (correctly indented for blueprint
            front-matter) representing the checks for that stack, or the
            default placeholder block when no stack was detected.
    """
    if (project_root / "go.mod").exists():
        return (
            "Go",
            "  - name: build\n    command: [\"go\", \"build\", \"./...\"]\n"
            "  - name: vet\n    command: [\"go\", \"vet\", \"./...\"]",
        )
    if (project_root / "pyproject.toml").exists() or (project_root / "setup.py").exists():
        return (
            "Python",
            "  - name: test\n    command: [\"pytest\", \"-q\"]",
        )
    if (project_root / "package.json").exists():
        return (
            "Node",
            "  - name: test\n    command: [\"npm\", \"test\"]",
        )
    if (project_root / "Cargo.toml").exists():
        return (
            "Rust",
            "  - name: check\n    command: [\"cargo\", \"check\"]",
        )
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
]

# Stack-specific security scanner, keyed by the stack's check_set name.
_SECURITY_SCANNERS: dict[str, tuple[str, list[str]]] = {
    "go": ("govulncheck", ["govulncheck", "./..."]),
    "python": ("pip-audit", ["pip-audit"]),
    "node": ("npm-audit", ["npm", "audit"]),
    "rust": ("cargo-audit", ["cargo", "audit"]),
}
# Secret scanning is not stack-specific, so it is always part of `security`.
_GITLEAKS_CHECK: tuple[str, list[str]] = ("gitleaks", ["gitleaks", "detect"])


def detect_stacks(project_root: Path) -> list[tuple[str, str, list[tuple[str, list[str]]]]]:
    """Detect every technology stack present, each with its full check battery.

    Unlike detect_stack() (first-match-wins, a single 2-tuple), this returns ONE
    entry per stack whose marker file(s) exist, so a polyglot project (e.g.
    pyproject.toml + package.json) is not silently reduced to a single stack.

    Args:
        project_root: Directory to inspect for marker files.

    Returns:
        A list of (stack_label, check_set_name, checks) tuples, one per detected
        stack, in marker precedence order (Go, Python, Node, Rust). `checks` is
        the full [(check_name, command), ...] battery for that stack.
    """
    return [
        (label, set_name, checks)
        for markers, label, set_name, checks in _STACK_DEFS
        if any((project_root / marker).exists() for marker in markers)
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


def _render_check_set(name: str, checks: list[tuple[str, list[str]]]) -> str:
    """Render one named check_sets entry as a manifest.yaml YAML block.

    A check whose binary is not found on PATH is written commented out — a
    live check that fails on a clean checkout would break every run. A set
    left with zero live checks still renders as an explicit empty list so the
    Manifest still parses.
    """
    lines = [f"  {name}:"]
    any_live = False
    for check_name, command in checks:
        commented = shutil.which(command[0]) is None
        prefix = "# " if commented else ""
        lines.append(f"    {prefix}- name: {check_name}")
        lines.append(f"    {prefix}  command: {json.dumps(command)}")
        any_live = any_live or not commented
    if not any_live:
        lines.insert(1, "    []")
    return "\n".join(lines)


def _render_check_sets_block(stacks: list[tuple[str, str, list[tuple[str, list[str]]]]]) -> str:
    """Render the full `check_sets:` mapping body for detected stacks + security."""
    check_sets = _build_check_sets(stacks)
    return "\n\n".join(_render_check_set(name, checks) for name, checks in check_sets.items())


# ---------------------------------------------------------------------------
# Scaffolder
# ---------------------------------------------------------------------------

def scaffold(project_root: Path, force: bool = False) -> list[str]:
    """Write the default Operator Layer into project_root/.alc/.

    Creates the full directory structure and all default template files from
    the built-in constants. The generated layer is conformant with the Policy
    Gate (alc lint passes with no error-level violations).

    The chore, bug, and feature blueprints receive real stack-specific checks
    when detect_stack() identifies the project stack; otherwise they keep the
    placeholder comment + smoke check.  plan.md always keeps the ["true"] smoke
    check because the planning stage produces no executable code.

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
    # (detect_stack) stays first-match-wins so the default blueprints keep
    # their current inline checks byte-identical; detect_stacks() separately
    # feeds the multi-stack check_sets below.
    _stack_label, checks_block = detect_stack(project_root)
    check_sets_block = _render_check_sets_block(detect_stacks(project_root))

    # Create directory structure.
    (alc_dir / "blueprints").mkdir(parents=True, exist_ok=True)
    (alc_dir / "flows").mkdir(parents=True, exist_ok=True)
    # Empty keyed prompt-override store — reserved prompts resolve to their
    # embedded defaults until an operator ejects/authors a file here.
    (alc_dir / "prompts").mkdir(parents=True, exist_ok=True)

    # Map each relative path to its content.
    files: dict[str, str] = {
        ".alc/manifest.yaml": _MANIFEST.format(check_sets_block=check_sets_block),
        ".alc/blueprints/chore.md": _CHORE.format(checks_block=checks_block),
        ".alc/blueprints/bug.md": _BUG.format(checks_block=checks_block),
        ".alc/blueprints/feature.md": _FEATURE.format(checks_block=checks_block),
        ".alc/blueprints/plan.md": _PLAN,
        ".alc/flows/ship.yaml": _SHIP,
    }

    for rel_path, content in files.items():
        (project_root / rel_path).write_text(content)

    return sorted(files.keys())
