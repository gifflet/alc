# checkconfig.py — The `check-config-integrity` guard: a deterministic, content-aware
# detector that turns an Act's edit to a CHECK-DEFINING file into a synthetic failed
# check, exactly parallel to `protect:`'s `protected-paths` guard (assurance.py).
#
# A run's checks are its LAW — the fixed bar the work must clear. An engine that
# cannot make the CODE pass can always make the LAW pass instead: widen an eslint
# ignore to swallow the offending files, delete a `[tool.ruff]` rule, rewrite a
# `test` script to `true`. The run then goes green having proven nothing, and the
# weakened law auto-lands. This guard makes that move tamper-EVIDENT (the operator
# always sees a run that touched check config) and tamper-RESISTANT (a run that
# silently weakens a check fails, so it never auto-commits/auto-merges — the
# existing checks-are-law gate does the rest).
#
# It deliberately never judges WHETHER an edit weakened the check — only that a
# law-defining file was touched — because the guard is REPAIRABLE: the engine is
# told to revert the config and fix the code instead, and can still finish green.
# "Touched the law" is a cheap, deterministic signal; "weakened the law" is not.
from __future__ import annotations

import shlex
import tomllib
from fnmatch import fnmatch
from pathlib import Path

from alc.harvest import read_package_scripts
from alc.models import Check

# Basename fnmatch patterns for files that DEFINE how a check behaves. Grouped by
# ecosystem, each group with the reason it belongs. Matched against a path's
# BASENAME only (a tool reads `eslint.config.mjs` wherever it sits), so a nested
# copy is caught as readily as a root one. NO lockfiles: a lockfile pins dependency
# versions, never a check's pass/fail bar, and it legitimately churns on any install.
CHECK_CONFIG_PATTERNS: tuple[str, ...] = (
    # Node/JS linters, type-checker, formatters, and test-runner configs — the
    # files deciding what `lint`/`typecheck`/`test` inspect and what they ignore.
    ".eslintrc*",
    "eslint.config.*",
    "biome.json*",
    "tsconfig*.json",
    "vitest.config.*",
    "jest.config.*",
    ".mocharc*",
    "playwright.config.*",
    ".prettierrc*",
    "prettier.config.*",
    # Task files: the recipe a check invokes (`make lint`, `just test`). Rewrite the
    # recipe body and the same check NAME now runs something else entirely.
    "Makefile",
    "makefile",
    "justfile",
    "Justfile",
    "Taskfile.yml",
    "Taskfile.yaml",
    # Git hooks / Python quality gates: what pre-commit, tox/nox, pytest, ruff,
    # mypy, and flake8 collect, select, and ignore.
    ".pre-commit-config.yaml",
    "tox.ini",
    "noxfile.py",
    "pytest.ini",
    "setup.cfg",
    "ruff.toml",
    ".ruff.toml",
    "mypy.ini",
    ".flake8",
    # Go / Rust: linter and formatter configs.
    ".golangci.yml",
    ".golangci.yaml",
    "clippy.toml",
    "rustfmt.toml",
)


def snapshot_check_manifests(workdir: Path) -> dict:
    """Snapshot the check-relevant SLICE of the two files that are BOTH a dependency
    manifest and a check config, so a later diff can tell a legitimate dependency
    bump apart from a check-weakening edit.

    ``package.json`` -> its ``scripts`` map (the check recipes); ``pyproject.toml``
    -> its ``[tool]`` table (ruff/mypy/pytest/... config). A plain basename match
    would fire on every ``npm install`` or ``uv add``; snapshotting only the
    check-relevant slice lets the detector stay silent when ONLY dependencies moved.

    Never raises: a missing or unparseable file snapshots as None (for pyproject) or
    an empty scripts map (for package.json, via the same graceful reader harvest
    uses). The detector treats a later inequality against this snapshot as a hit.
    """
    return {
        "package.json": _package_scripts_or_none(workdir),
        "pyproject.toml": _pyproject_tool_or_none(workdir),
    }


def check_referenced_files(checks: list[Check], workdir: Path) -> set[str]:
    """Return the workdir-relative paths of EXISTING regular files a check's own
    command names — a check's script is as much "the law" as the check line itself.

    A check like ``["python", "scripts/bench.py"]`` or a ``metric`` that shells out
    to a benchmark rig can be neutered by editing that script instead of the check;
    surfacing those files lets ``detect_check_config_edits`` catch such an edit.

    Tokenizes each check's ``command`` (argv), ``shell`` one-liner (``shlex.split``;
    a malformed quote raises ValueError -> that check is skipped, never fatal), and
    ``metric`` (argv list or shell string, same shape rules as command/shell). A
    token counts only when it resolves to an existing regular file under workdir —
    binaries on PATH and flags never do.
    """
    referenced: set[str] = set()
    for check in checks:
        for token in _check_tokens(check):
            rel = _resolve_under_workdir(token, workdir)
            if rel is not None:
                referenced.add(rel)
    return referenced


def detect_check_config_edits(
    changed: list[str],
    workdir: Path,
    snapshot: dict,
    referenced: set[str],
) -> list[str]:
    """Return ``"path (reason)"`` strings for every changed path that touched the law.

    A hit is any of: a basename that matches ``CHECK_CONFIG_PATTERNS``; the root
    ``package.json`` whose ``scripts`` slice moved vs *snapshot* (a dependency-only
    change is clean; scripts appearing/vanishing/becoming unparseable is a hit); the
    root ``pyproject.toml`` whose ``[tool]`` table moved vs *snapshot* (a
    ``[project]``/dependency change is clean); or any changed path in *referenced*.

    Paths under ``.alc/`` are filtered out defensively — the Operator Layer is
    already always-protected (the engine cannot commit to it), so it must never be
    double-reported here.
    """
    hits: list[str] = []
    for path in changed:
        # .alc/ is already always-protected — never double-report it here.
        if path.startswith(".alc/"):
            continue
        basename = Path(path).name
        if any(fnmatch(basename, pattern) for pattern in CHECK_CONFIG_PATTERNS):
            hits.append(f"{path} (check config)")
            continue
        if path == "package.json":
            reason = _package_json_reason(workdir, snapshot.get("package.json"))
            if reason is not None:
                hits.append(f"{path} ({reason})")
            continue
        if path == "pyproject.toml":
            reason = _pyproject_reason(workdir, snapshot.get("pyproject.toml"))
            if reason is not None:
                hits.append(f"{path} ({reason})")
            continue
        if path in referenced:
            hits.append(f"{path} (check-referenced file)")
    return hits


# ---------------------------------------------------------------------------
# Internal helpers — all graceful: a missing/unparseable file is data, not an error.
# ---------------------------------------------------------------------------


def _package_scripts_or_none(workdir: Path) -> dict[str, str] | None:
    """The ``scripts`` map from *workdir*'s package.json, or None when it is absent.

    Reuses harvest's safe, execute-free reader — which returns ``{}`` when the file
    exists but has no scripts or cannot be parsed. None (file absent) and ``{}``
    (present but scriptless/unparseable) are DISTINCT so a snapshot-vs-current diff
    can tell "appeared" from "scripts emptied".
    """
    if not (workdir / "package.json").exists():
        return None
    return read_package_scripts(workdir)


def _package_json_reason(workdir: Path, snapshot_scripts: dict | None) -> str | None:
    """Return a reason when package.json's scripts slice moved vs the snapshot, else
    None (only dependencies changed -> the check recipes are intact -> clean)."""
    if _package_scripts_or_none(workdir) == snapshot_scripts:
        return None
    return "check scripts changed"


def _pyproject_tool_or_none(workdir: Path) -> dict | None:
    """The ``[tool]`` table from *workdir*'s pyproject.toml, or None when the file
    is absent or cannot be parsed (a config that cannot be read cannot be trusted —
    the detector treats that as a change)."""
    path = workdir / "pyproject.toml"
    if not path.exists():
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # tomllib.TOMLDecodeError subclasses ValueError; OSError covers read errors.
        return None
    tool = data.get("tool")
    return tool if isinstance(tool, dict) else {}


def _pyproject_reason(workdir: Path, snapshot_tool: dict | None) -> str | None:
    """Return a reason when pyproject's [tool] table moved vs the snapshot, else None
    (a [project]/dependency change leaves the check config intact -> clean)."""
    if _pyproject_tool_or_none(workdir) == snapshot_tool:
        return None
    return "[tool] config changed"


def _check_tokens(check: Check) -> list[str]:
    """Every argv-ish token a check runs: command, shell (split), and metric."""
    tokens: list[str] = []
    if check.command:
        tokens.extend(check.command)
    if check.shell:
        tokens.extend(_safe_split(check.shell))
    if check.metric is not None:
        if isinstance(check.metric, list):
            tokens.extend(check.metric)
        else:
            tokens.extend(_safe_split(check.metric))
    return tokens


def _safe_split(text: str) -> list[str]:
    """shlex.split that degrades to [] on an unbalanced quote instead of raising —
    a malformed check fails on its own merits; it must not break the guard."""
    try:
        return shlex.split(text)
    except ValueError:
        return []


def _resolve_under_workdir(token: str, workdir: Path) -> str | None:
    """Return *token*'s workdir-relative path when it names an EXISTING regular file
    inside workdir, else None. Flags, binaries on PATH, absolute paths, and tokens
    escaping the tree via ``..`` all fall through to None."""
    if not token or token.startswith("-"):
        return None
    candidate = workdir / token
    try:
        if not candidate.is_file():
            return None
        rel = candidate.resolve().relative_to(workdir.resolve())
    except (OSError, ValueError):
        return None
    return str(rel)
