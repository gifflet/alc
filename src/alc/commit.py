# commit.py — Workdir-scoped terminal commit for a Flow.
# A committing Flow lands EXACTLY its workdir's changes as one clean control-plane
# commit on success. Scoping the commit to the workdir (relative to that workdir's
# HEAD) is what makes it parallel-ready: an isolated worktree commits only its own
# demand's changes, with no cross-contamination.
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _git_toplevel(workdir: Path) -> Path | None:
    """Return the git toplevel for *workdir*, or None if not in a git repo."""
    try:
        result = subprocess.run(
            ["git", "-C", str(workdir), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def _resolve_workdir(workdir: Path) -> Path | None:
    """Resolve *workdir* to the git toplevel, warning if it diverges.

    The root-anchored magic pathspec ``:(exclude).alc/`` only excludes correctly
    when the operation runs from the git toplevel. If *workdir* resolves to a
    different path the caller is warned and the toplevel is used instead.

    Returns None when *workdir* is not inside a git repository (callers treat
    that as a no-op — no git means no dirt and no commit).
    """
    toplevel = _git_toplevel(workdir)
    if toplevel is None:
        return None
    try:
        resolved = workdir.resolve()
    except OSError:
        resolved = workdir
    if resolved != toplevel.resolve():
        print(
            f"[commit] WARN: workdir {workdir} is not the git toplevel "
            f"({toplevel}); operating against the toplevel.",
            file=sys.stderr,
        )
    return toplevel


def has_non_alc_changes(workdir: Path) -> bool:
    """Return True if *workdir* has uncommitted changes outside ``.alc/``.

    Backs the clean-tree guard for a committing Flow in shared (non-isolated) mode:
    pre-existing non-``.alc/`` dirt must abort the Flow so the terminal commit never
    sweeps unrelated work. Returns False when *workdir* is not a git repo or git is
    unavailable (no dirt to protect against — the guard is a no-op there).

    The check is always run against the git toplevel so the root-anchored pathspec
    ``:(exclude).alc/`` resolves correctly.
    """
    root = _resolve_workdir(workdir)
    if root is None:
        return False

    try:
        result = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False
    if result.returncode != 0:
        return False

    for line in result.stdout.splitlines():
        # Porcelain v1: "XY path" (path starts at col 3). Renames use " -> ".
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if not path.startswith(".alc/"):
            return True
    return False


def commit_workdir(
    workdir: Path,
    message: str,
    exclude: tuple[str, ...] = (".alc/",),
) -> str | None:
    """Stage and commit everything in *workdir* (except *exclude*), return the sha.

    Two-step staging strategy:
    1. ``git add -A`` — stages all non-ignored changes; exits 0 and silently skips
       ignored files regardless of whether any exclude entry appears in .gitignore.
       Using the ``:(exclude)`` pathspec here triggers an "ignored path" warning and
       exit 1 when the excluded path is listed in .gitignore, which is the bug this
       approach avoids.
    2. For each *exclude* entry: ``git reset -q -- <entry>`` — unstages anything that
       was staged under that prefix (covers tracked-but-now-gitignored files that
       ``git add -A`` would otherwise include).

    Then commits only when something is actually staged (never creates an empty
    commit). The *message* is passed to git verbatim (a list argv, no shell) — the
    caller supplies a clean message with NO Co-Authored-By trailer.

    Always operates against the git toplevel. Returns None (with a stderr warning)
    when *workdir* is not inside a git repo.

    Args:
        workdir: Directory to stage and commit in (the Flow's shared workdir).
        message: The commit message, used verbatim.
        exclude: Path prefixes to keep out of the commit (default: the ``.alc/``
            control-plane state, which must never land in a demand's commit).

    Returns:
        The new commit's sha, or None when there is nothing to commit or any git
        step fails (a commit failure must never crash the Flow).
    """
    root = _resolve_workdir(workdir)
    if root is None:
        return None

    try:
        # Step 1: stage everything git does not ignore (no pathspec avoids the
        # "ignored path" exit-1 that the :(exclude) form triggers).
        add = subprocess.run(
            ["git", "-C", str(root), "add", "-A"],
            capture_output=True,
            text=True,
        )
        if add.returncode != 0:
            print(
                f"[commit] git add failed in {root}: {add.stderr.strip()}",
                file=sys.stderr,
            )
            return None

        # Step 2: unstage excluded prefixes (handles tracked files under .alc/ that
        # git add -A would otherwise include because they are tracked).
        for entry in exclude:
            subprocess.run(
                ["git", "-C", str(root), "reset", "-q", "--", entry],
                capture_output=True,
            )

        # Nothing staged -> exit 0 -> skip the commit (no empty commits).
        diff = subprocess.run(
            ["git", "-C", str(root), "diff", "--cached", "--quiet"],
            capture_output=True,
        )
        if diff.returncode == 0:
            return None

        commit = subprocess.run(
            ["git", "-C", str(root), "commit", "-m", message],
            capture_output=True,
            text=True,
        )
        if commit.returncode != 0:
            print(
                f"[commit] git commit failed in {root}: {commit.stderr.strip()}",
                file=sys.stderr,
            )
            return None

        rev = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
        )
        if rev.returncode != 0:
            return None
        return rev.stdout.strip()
    except FileNotFoundError:
        # git not installed — never raise out of a terminal commit.
        print("[commit] git not found; skipping terminal commit.", file=sys.stderr)
        return None
