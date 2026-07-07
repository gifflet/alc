# scaffold.py — Built-in default templates and the scaffolder for `alc init`.
# Writes a conformant Operator Layer (.alc/) into a project root from in-module
# string constants — no package-data configuration required.
from __future__ import annotations

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

    # Detect the project stack to provide real checks.
    _stack_label, checks_block = detect_stack(project_root)

    # Create directory structure.
    (alc_dir / "blueprints").mkdir(parents=True, exist_ok=True)
    (alc_dir / "flows").mkdir(parents=True, exist_ok=True)

    # Map each relative path to its content.
    files: dict[str, str] = {
        ".alc/manifest.yaml": _MANIFEST,
        ".alc/blueprints/chore.md": _CHORE.format(checks_block=checks_block),
        ".alc/blueprints/bug.md": _BUG.format(checks_block=checks_block),
        ".alc/blueprints/feature.md": _FEATURE.format(checks_block=checks_block),
        ".alc/blueprints/plan.md": _PLAN,
        ".alc/flows/ship.yaml": _SHIP,
    }

    for rel_path, content in files.items():
        (project_root / rel_path).write_text(content)

    return sorted(files.keys())
