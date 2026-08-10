# pydeps.py — read-only readers for a Python project's environment manager.
#
# A lockfile proves which env manager a project uses (uv, poetry, pdm, pipenv),
# and its contents prove which tools that environment can actually provide. That
# pair lets `alc init` scaffold a locked tool LIVE through its runner
# (`uv run pytest -q`) instead of commenting out a bare `pytest` that only
# exists inside the project's .venv — the exact "tool behind a venv/wrapper"
# case render_blueprint_checks documents.
#
# HARD SAFETY INVARIANT (same as harvest.py): this module only PARSES files —
# it NEVER executes a project command. A missing or malformed lockfile degrades
# to "no runner / nothing locked", which keeps today's conservative behavior.
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

# Lockfile -> the argv prefix that runs a tool inside the project's environment,
# in precedence order (uv first: it is the most common alongside a stray
# poetry.lock left behind by a migration).
_PYTHON_RUNNERS: list[tuple[str, list[str]]] = [
    ("uv.lock", ["uv", "run"]),
    ("poetry.lock", ["poetry", "run"]),
    ("pdm.lock", ["pdm", "run"]),
    ("Pipfile.lock", ["pipenv", "run"]),
]

_NORMALIZE_RE = re.compile(r"[-_.]+")


def _normalize(name: str) -> str:
    """PEP 503 package-name normalization (lowercase, runs of -_. become -)."""
    return _NORMALIZE_RE.sub("-", name).lower()


def python_runner(project_root: Path) -> list[str]:
    """The argv prefix that runs a tool inside *project_root*'s Python env.

    Chosen by lockfile presence, mirroring how harvest's `_node_runner` picks
    pnpm/yarn/npm. Returns [] when no known lockfile is present — the caller
    keeps the bare command exactly as before.
    """
    for lockfile, runner in _PYTHON_RUNNERS:
        if (project_root / lockfile).exists():
            return runner
    return []


def _toml_package_names(path: Path) -> frozenset[str]:
    """Normalized `[[package]] name` entries of a uv/poetry/pdm lockfile."""
    data = tomllib.loads(path.read_text())
    packages = data.get("package")
    if not isinstance(packages, list):
        return frozenset()
    return frozenset(
        _normalize(entry["name"])
        for entry in packages
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    )


def _pipfile_package_names(path: Path) -> frozenset[str]:
    """Normalized keys of Pipfile.lock's `default` + `develop` sections."""
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        return frozenset()
    names: set[str] = set()
    for section in ("default", "develop"):
        packages = data.get(section)
        if isinstance(packages, dict):
            names.update(_normalize(name) for name in packages if isinstance(name, str))
    return frozenset(names)


def locked_packages(project_root: Path) -> frozenset[str]:
    """Normalized package names locked by *project_root*'s Python env manager.

    Reads the same lockfile `python_runner` keyed on. Degrades to an empty set
    — never raises — when no lockfile is present or it cannot be parsed, so a
    caller never wraps a tool the lockfile cannot vouch for.
    """
    for lockfile, _runner in _PYTHON_RUNNERS:
        path = project_root / lockfile
        if not path.exists():
            continue
        parse = _pipfile_package_names if lockfile == "Pipfile.lock" else _toml_package_names
        try:
            return parse(path)
        except (OSError, tomllib.TOMLDecodeError, json.JSONDecodeError):
            return frozenset()
    return frozenset()


def resolve_python_checks(
    checks: list[tuple[str, list[str]]], project_root: Path
) -> list[tuple[str, list[str]]]:
    """Rewrite a static Python battery against the project's REAL environment.

    Each check whose binary (argv[0]) is a package the project's lockfile
    declares is prefixed with the env manager's runner — `pytest -q` becomes
    `uv run pytest -q` — so availability keys on the runner (which IS on PATH)
    and the check runs inside the project's own environment on a clean checkout
    (after `uv sync` / `poetry install`).

    The lockfile lookup is the honesty gate: a tool the lockfile does NOT
    declare stays bare, because wrapping it would scaffold a live check that
    fails on a clean checkout (`uv run ruff` with no ruff dependency). Assumes
    the console-script name matches its package name — true for every tool ALC
    scaffolds (pytest, ruff, pip-audit). Without a lockfile this is identity.
    """
    runner = python_runner(project_root)
    if not runner:
        return list(checks)
    locked = locked_packages(project_root)
    return [
        (name, [*runner, *command] if _normalize(command[0]) in locked else command)
        for name, command in checks
    ]


# Runner binary -> the command that materializes its locked environment. Keys
# mirror _PYTHON_RUNNERS' argv[0]s; used to make an availability hint actionable.
_RUNNER_SYNC: dict[str, str] = {
    "uv": "uv sync",
    "poetry": "poetry install",
    "pdm": "pdm install",
    "pipenv": "pipenv install --dev",
}

# The package-name prefix of a PEP 508 requirement string ("pytest>=8",
# "pytest-cov[toml]==5.0" -> "pytest", "pytest-cov").
_REQUIREMENT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")


def declared_packages(project_root: Path) -> frozenset[str]:
    """Normalized package names *project_root*'s pyproject.toml declares.

    Reads [project.dependencies], every [project.optional-dependencies] group,
    and every PEP 735 [dependency-groups] group (skipping {include-group}
    table entries — the group they point at is read directly anyway). Degrades
    to an empty set — never raises — on a missing or malformed pyproject.
    """
    path = project_root / "pyproject.toml"
    if not path.exists():
        return frozenset()
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return frozenset()

    requirements: list[object] = []
    project = data.get("project")
    if isinstance(project, dict):
        if isinstance(project.get("dependencies"), list):
            requirements += project["dependencies"]
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            for group in optional.values():
                if isinstance(group, list):
                    requirements += group
    groups = data.get("dependency-groups")
    if isinstance(groups, dict):
        for group in groups.values():
            if isinstance(group, list):
                requirements += group

    names: set[str] = set()
    for requirement in requirements:
        if not isinstance(requirement, str):
            continue  # an {include-group = ...} table entry
        match = _REQUIREMENT_NAME_RE.match(requirement.strip())
        if match:
            names.add(_normalize(match.group(0)))
    return frozenset(names)


def unavailable_hint(project_root: Path, command: list[str]) -> str | None:
    """An actionable install hint for an off-PATH check command, or None.

    Distinguishes "the project DOES provide this, your environment just isn't
    materialized" from "not a tool this project uses" (which stays hint-less):

    - argv[0] is the project's env-manager runner (`uv run ...` with uv itself
      off PATH): the gap is the MANAGER — install it, then sync.
    - argv[0] is a package pyproject.toml declares: it arrives with the
      project's own dev dependencies, not a global install.
    """
    if not command:
        return None
    tool = command[0]
    runner = python_runner(project_root)
    if runner and tool == runner[0]:
        return f"install {tool} — the project's env manager — then run `{_RUNNER_SYNC[tool]}`"
    if _normalize(tool) in declared_packages(project_root):
        if runner:
            return f"declared in pyproject.toml — run `{_RUNNER_SYNC[runner[0]]}` to install it"
        return "declared in pyproject.toml — install the project's dev dependencies"
    return None
