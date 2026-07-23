# branches.py — Pure git helpers over `alc/*` branches.
# Every worktree-owning commit (run / flow / tick / conduct) lands on a branch
# named `alc/<label>-<hex8>` (see worktree.py:IsolatedWorktree.branch). This
# module enumerates, inspects and deletes those branches; consumed by `land`,
# `discard` and `status` (Wave 2+). Never raises on a missing `git` (mirrors
# merge.py:79-85) — it degrades to an empty/no-op result instead.
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# `alc/<label>-<hex8>`: label is everything between the prefix and the trailing
# 8-hex-char suffix minted by IsolatedWorktree (`uuid.uuid4().hex[:8]`).
_BRANCH_RE = re.compile(r"^alc/(?P<label>.+)-(?P<hex>[0-9a-f]{8})$")


@dataclass(frozen=True)
class AlcBranch:
    """One `alc/*` branch: its name, provenance label, and merge status."""

    name: str            # full branch name, e.g. "alc/tick-a1b2c3d4"
    label: str           # provenance segment, e.g. "run"/"flow"/"tick"/"conduct"
    committed_at: float  # epoch seconds of the branch tip's committer date
    merged: bool         # already contained in HEAD


def _label_for(name: str) -> str:
    """Extract the provenance label from an `alc/<label>-<hex8>` branch name."""
    match = _BRANCH_RE.match(name)
    return match.group("label") if match else name.removeprefix("alc/")


def _contained_in_head(repo_root: Path, branch: str) -> bool:
    """True when *branch* is already contained in HEAD (mirrors merge.py).

    An empty ``git rev-list HEAD..<branch>`` means HEAD already has every
    commit the branch does — nothing left to integrate.
    """
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-list", f"HEAD..{branch}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Ref can't be read (missing/ambiguous) — treat as not (yet) merged.
        return False
    return result.stdout.strip() == ""


def list_alc_branches(repo_root: Path) -> list[AlcBranch]:
    """Enumerate every `alc/*` branch, in the order `git for-each-ref` returns.

    Never raises: a missing ``git`` binary, or a repo with no `alc/*` branches,
    both yield an empty list.
    """
    try:
        result = subprocess.run(
            [
                "git", "-C", str(repo_root), "for-each-ref", "refs/heads/alc/",
                "--format=%(refname:short)%09%(committerdate:unix)",
            ],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print("[branches] git not found; no alc/ branches listed.", file=sys.stderr)
        return []
    if result.returncode != 0:
        return []

    branches = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        name, _, committed_at = line.partition("\t")
        branches.append(
            AlcBranch(
                name=name,
                label=_label_for(name),
                committed_at=float(committed_at) if committed_at else 0.0,
                merged=_contained_in_head(repo_root, name),
            )
        )
    return branches


def delete_branches(repo_root: Path, names: list[str]) -> list[str]:
    """Force-delete each of *names* that is an `alc/` branch and not the current one.

    A ref outside the `alc/` prefix, or the currently checked-out branch, is
    silently skipped — never deleted. Returns the names actually deleted.
    Never raises: a missing ``git`` binary yields an empty result.
    """
    try:
        current = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print("[branches] git not found; nothing deleted.", file=sys.stderr)
        return []
    current_branch = current.stdout.strip() if current.returncode == 0 else None

    deleted: list[str] = []
    for name in names:
        if not name.startswith("alc/") or name == current_branch:
            continue
        result = subprocess.run(
            ["git", "-C", str(repo_root), "branch", "-D", name],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            deleted.append(name)
    return deleted


def prune_worktrees(repo_root: Path) -> int:
    """Remove stale worktree admin entries; return the count pruned.

    Never raises: a missing ``git`` binary is treated as nothing to prune.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "worktree", "prune", "-v"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print("[branches] git not found; nothing pruned.", file=sys.stderr)
        return 0
    if result.returncode != 0:
        return 0
    # `-v` reports one "Removing ..." line per pruned entry, on stderr.
    return len([ln for ln in result.stderr.splitlines() if ln.strip()])
