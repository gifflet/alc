# harvest.py — the deterministic HARVEST layer for a future `alc onboard`.
#
# A pure, READ-ONLY scan of a project for the check commands it ALREADY declares
# — package.json scripts, Makefile/justfile/Taskfile targets, pre-commit, tox and
# nox — so ALC can adopt the project's own checks instead of inventing them. This
# module is a leaf: it writes nothing, and it never touches the CLI or Manifest
# (those are separate later steps).
#
# HARD SAFETY INVARIANT: harvesting NEVER executes a project command. It only
# PARSES files and uses `shutil.which` to test whether a tool is on PATH (a
# lookup, not an execution) — exactly as `scaffold._render_check_set` and
# `checks.audit_checks` already do.
#
# Deliberately OUT OF SCOPE here (a disciplined future addition, ranks 5-6 of the
# design): CI-config parsing (.github/workflows, .gitlab-ci) and linter-config
# detection. Only the high-confidence, explicitly-declared checks above are
# harvested in this module.
from __future__ import annotations

import configparser
import json
import re
import shlex
import shutil
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from alc.textutil import slugify

# ---------------------------------------------------------------------------
# Data model (mirrors the checks.py dataclass idiom)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HarvestedCheck:
    """One check ALC could adopt, harvested from a declaration the project
    already ships. Exactly one of ``command`` (a clean argv token list) or
    ``shell`` (a string needing a shell) is set."""

    name: str                       # slugified, de-collided
    command: list[str] | None       # argv form, when the command is a clean token list
    shell: str | None               # shell form, when it needs a shell
    source: str                     # e.g. "package-json" | "makefile" | "tox"
    source_path: str                # repo-relative file it came from
    confidence: str                 # "high" for every source in this module
    available: bool                 # the tool's binary is on PATH (shutil.which)


@dataclass(frozen=True)
class HarvestReport:
    """The full result of a harvest. Nothing here is written to disk."""

    checks: list[HarvestedCheck]
    scanned: list[str]              # repo-relative files that were parsed
    skipped: list[str]              # present-but-unparseable files, reason appended


# ---------------------------------------------------------------------------
# Check-ish name sets — only these declared names are worth adopting.
# ---------------------------------------------------------------------------

# package.json `scripts` keys.
_PACKAGE_CHECKISH = frozenset(
    {"test", "lint", "typecheck", "check", "build", "ci", "format", "fmt"}
)

# Makefile / justfile / Taskfile target names.
_TARGET_CHECKISH = frozenset(
    {
        "test", "lint", "check", "fmt", "format", "typecheck",
        "vet", "build", "ci", "tests", "lint-fix",
    }
)

# Sources whose checks name a project TASK ("test", "lint", ...); several of them
# declaring the same task is the same underlying check, so they dedup by name.
_NAMED_TASK_SOURCES = frozenset({"package-json", "makefile", "justfile", "taskfile"})

_MAKE_TARGET_RE = re.compile(r"^([A-Za-z][\w.-]*):")
_JUST_RECIPE_RE = re.compile(r"^([a-z][\w-]*):")
_NOX_SESSION_RE = re.compile(
    r"@nox\.session[^\n]*\n(?:[ \t]*@[^\n]*\n)*[ \t]*def[ \t]+(\w+)[ \t]*\(",
)


# ---------------------------------------------------------------------------
# Small shared utilities
# ---------------------------------------------------------------------------


def _first_existing(project_root: Path, names: list[str]) -> Path | None:
    """Return the first of *names* that exists directly under *project_root*."""
    for name in names:
        path = project_root / name
        if path.exists():
            return path
    return None


def _available(command: list[str] | None, shell: str | None) -> bool:
    """True when the check's tool (argv[0], or the first shell token) is on PATH.

    A `shutil.which` LOOKUP — never an execution; see the module safety invariant.
    """
    token: str | None = None
    if command:
        token = command[0]
    elif shell:
        parts = shlex.split(shell)
        token = parts[0] if parts else None
    return token is not None and shutil.which(token) is not None


def _make_check(
    name: str,
    command: list[str],
    source: str,
    source_path: str,
) -> HarvestedCheck:
    """Build a high-confidence, argv-form HarvestedCheck with `available` filled.

    ``name`` is provisional (the raw script/target/env name); `harvest` slugifies
    and de-collides it during normalization.
    """
    return HarvestedCheck(
        name=name,
        command=command,
        shell=None,
        source=source,
        source_path=source_path,
        confidence="high",
        available=_available(command, None),
    )


# ---------------------------------------------------------------------------
# Per-source harvesters — each isolated and graceful: a malformed/unreadable
# file appends a short reason to `skipped` and contributes zero checks; it never
# raises. Each returns (checks, scanned, skipped).
# ---------------------------------------------------------------------------

_HarvestResult = tuple[list[HarvestedCheck], list[str], list[str]]


def _parse_package_scripts(project_root: Path) -> tuple[dict[str, str], str | None]:
    """Read package.json and return (scripts_map, skip_reason).

    A read-only, safe JSON parse — it NEVER executes a script (see the module
    safety invariant). `scripts_map` is the (string-keyed) `scripts` mapping, or
    `{}` when the file is missing, has no `scripts`, or `scripts` is not a map.
    `skip_reason` is set ONLY when package.json exists but cannot be parsed, so a
    caller that reports scanned-vs-skipped can tell "malformed" from "no scripts".
    """
    path = project_root / "package.json"
    if not path.exists():
        return {}, None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {}, f"invalid JSON ({type(exc).__name__})"
    scripts = data.get("scripts") if isinstance(data, dict) else None
    if not isinstance(scripts, dict):
        return {}, None
    return {k: v for k, v in scripts.items() if isinstance(k, str)}, None


def read_package_scripts(project_root: Path) -> dict[str, str]:
    """The `scripts` map from *project_root*'s package.json, or `{}` on any problem.

    A graceful, names-only reader that never raises and never executes a script.
    Shared with `alc.scaffold` so `alc init` resolves Node checks against the
    project's REAL scripts the exact same safe way harvest reads them here.
    """
    scripts, _skip = _parse_package_scripts(project_root)
    return scripts


def _harvest_package_json(project_root: Path) -> _HarvestResult:
    """package.json `scripts`: check-ish keys via the project's package runner
    (`npm run`, or `pnpm run` / `yarn` when the matching lockfile is present)."""
    path = project_root / "package.json"
    if not path.exists():
        return [], [], []
    rel = "package.json"
    scripts, skip_reason = _parse_package_scripts(project_root)
    if skip_reason is not None:
        return [], [], [f"{rel}: {skip_reason}"]
    runner = _node_runner(project_root)
    checks = [
        _make_check(key, [*runner, key], "package-json", rel)
        for key in scripts
        if key in _PACKAGE_CHECKISH
    ]
    return checks, [rel], []


def _node_runner(project_root: Path) -> list[str]:
    """The package runner to invoke a script with, chosen by lockfile."""
    if (project_root / "pnpm-lock.yaml").exists():
        return ["pnpm", "run"]
    if (project_root / "yarn.lock").exists():
        return ["yarn"]
    return ["npm", "run"]


def _harvest_recipe_targets(
    project_root: Path,
    filenames: list[str],
    pattern: re.Pattern[str],
    tool: str,
    source: str,
) -> _HarvestResult:
    """Shared target-name scanner for Makefile/justfile: match *pattern* per line
    (TARGET NAMES only, never recipe bodies) and keep check-ish names."""
    path = _first_existing(project_root, filenames)
    if path is None:
        return [], [], []
    rel = str(path.relative_to(project_root))
    try:
        text = path.read_text()
    except OSError as exc:
        return [], [], [f"{rel}: unreadable ({type(exc).__name__})"]
    checks: list[HarvestedCheck] = []
    seen: set[str] = set()
    for line in text.splitlines():
        match = pattern.match(line)
        if match is None:
            continue
        target = match.group(1)
        if target not in _TARGET_CHECKISH or target in seen:
            continue
        seen.add(target)
        checks.append(_make_check(target, [tool, target], source, rel))
    return checks, [rel], []


def _harvest_makefile(project_root: Path) -> _HarvestResult:
    return _harvest_recipe_targets(
        project_root, ["Makefile", "makefile"], _MAKE_TARGET_RE, "make", "makefile"
    )


def _harvest_justfile(project_root: Path) -> _HarvestResult:
    return _harvest_recipe_targets(
        project_root, ["justfile", "Justfile"], _JUST_RECIPE_RE, "just", "justfile"
    )


def _harvest_taskfile(project_root: Path) -> _HarvestResult:
    """Taskfile.yml `tasks:` keys that are check-ish → `task <name>`."""
    path = _first_existing(project_root, ["Taskfile.yml", "Taskfile.yaml"])
    if path is None:
        return [], [], []
    rel = str(path.relative_to(project_root))
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        return [], [], [f"{rel}: unparseable ({type(exc).__name__})"]
    tasks = data.get("tasks") if isinstance(data, dict) else None
    if not isinstance(tasks, dict):
        return [], [rel], []
    checks = [
        _make_check(name, ["task", name], "taskfile", rel)
        for name in tasks
        if isinstance(name, str) and name in _TARGET_CHECKISH
    ]
    return checks, [rel], []


def _harvest_pre_commit(project_root: Path) -> _HarvestResult:
    """A present `.pre-commit-config.yaml` → one `pre-commit run --all-files`."""
    path = project_root / ".pre-commit-config.yaml"
    if not path.exists():
        return [], [], []
    rel = ".pre-commit-config.yaml"
    check = _make_check(
        "pre-commit", ["pre-commit", "run", "--all-files"], "pre-commit", rel
    )
    return [check], [rel], []


def _harvest_tox_nox(project_root: Path) -> _HarvestResult:
    """tox.ini envlist → `tox -e <env>`; noxfile.py sessions → `nox -s <name>`."""
    checks: list[HarvestedCheck] = []
    scanned: list[str] = []
    skipped: list[str] = []
    for helper in (_harvest_tox, _harvest_nox):
        part_checks, part_scanned, part_skipped = helper(project_root)
        checks += part_checks
        scanned += part_scanned
        skipped += part_skipped
    return checks, scanned, skipped


def _harvest_tox(project_root: Path) -> _HarvestResult:
    path = project_root / "tox.ini"
    if not path.exists():
        return [], [], []
    rel = "tox.ini"
    parser = configparser.ConfigParser()
    try:
        parser.read_string(path.read_text())
    except (OSError, configparser.Error) as exc:
        return [], [], [f"{rel}: unparseable ({type(exc).__name__})"]
    envlist = parser.get("tox", "envlist", fallback="")
    envs = [env for env in re.split(r"[,\s]+", envlist) if env]
    checks = [_make_check(env, ["tox", "-e", env], "tox", rel) for env in envs]
    return checks, [rel], []


def _harvest_nox(project_root: Path) -> _HarvestResult:
    path = project_root / "noxfile.py"
    if not path.exists():
        return [], [], []
    rel = "noxfile.py"
    try:
        text = path.read_text()
    except OSError as exc:
        return [], [], [f"{rel}: unreadable ({type(exc).__name__})"]
    checks: list[HarvestedCheck] = []
    seen: set[str] = set()
    for name in _NOX_SESSION_RE.findall(text):
        if name in seen:
            continue
        seen.add(name)
        checks.append(_make_check(name, ["nox", "-s", name], "nox", rel))
    return checks, [rel], []


# ---------------------------------------------------------------------------
# Normalization + dedup (pure)
# ---------------------------------------------------------------------------


def _dedup_key(check: HarvestedCheck) -> tuple[str, object]:
    """Comparison key that collapses duplicate declarations.

    Named-task sources ("test"/"lint"/... from a package runner or a target file)
    are the same underlying check when they share a name, so they key on that
    name. Every other source keys on its literal command, so genuinely distinct
    envs/sessions that merely slugify alike are NOT collapsed (the de-collider
    keeps their names unique instead).
    """
    if check.source in _NAMED_TASK_SOURCES:
        return ("task", slugify(check.name))
    if check.command is not None:
        return ("cmd", tuple(check.command))
    return ("shell", check.shell)


def _normalize(checks: list[HarvestedCheck]) -> list[HarvestedCheck]:
    """Dedup by canonical key (first occurrence wins), then slugify + de-collide
    names so no two returned checks ever share a `name`."""
    deduped: list[HarvestedCheck] = []
    seen_keys: set[tuple[str, object]] = set()
    for check in checks:
        key = _dedup_key(check)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(check)

    result: list[HarvestedCheck] = []
    used_names: set[str] = set()
    for check in deduped:
        base = slugify(check.name) or "check"
        name = base
        suffix = 2
        while name in used_names:
            name = f"{base}-{suffix}"
            suffix += 1
        used_names.add(name)
        result.append(replace(check, name=name))
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Ordered so the "direct" package-runner/target form wins a dedup tie over a
# less-direct declaration of the same task.
_HARVESTERS = (
    _harvest_package_json,
    _harvest_makefile,
    _harvest_justfile,
    _harvest_taskfile,
    _harvest_pre_commit,
    _harvest_tox_nox,
)


def harvest(project_root: Path) -> HarvestReport:
    """Scan *project_root* for the check commands it already declares.

    Runs every per-source harvester, concatenates their checks, then normalizes
    and dedups. Purely read-only: it parses files and calls `shutil.which`, and
    NEVER executes a project command.

    Args:
        project_root: Directory to scan for declared checks.

    Returns:
        A HarvestReport — its `checks` are the adoptable checks, `scanned` the
        files that parsed, and `skipped` the present-but-unparseable files with a
        short reason. Nothing is written to disk.
    """
    checks: list[HarvestedCheck] = []
    scanned: list[str] = []
    skipped: list[str] = []
    for harvester in _HARVESTERS:
        part_checks, part_scanned, part_skipped = harvester(project_root)
        checks += part_checks
        scanned += part_scanned
        skipped += part_skipped
    return HarvestReport(checks=_normalize(checks), scanned=scanned, skipped=skipped)
