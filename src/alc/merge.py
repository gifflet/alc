# merge.py — Post-batch auto-merge of the passed demand branches into main.
# After the parallel demand batch, each SUCCESSFUL demand's branch (alc/tick-<hex>,
# produced by the worktree exit-commit) is merged back into the current branch,
# SEQUENTIALLY. A clean merge deletes the now-merged branch; a conflict aborts the
# merge and LEAVES the branch for the operator to resolve — never a silent clobber.
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MergeReport:
    """Outcome of an auto-merge pass over a set of demand branches.

    Attributes:
        merged: Branches merged into the current branch, then deleted (sorted order).
        conflicted: Branches left intact for the operator to resolve manually.
    """

    merged: list[str] = field(default_factory=list)
    conflicted: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """Return a one-line human summary of the pass (printed by the caller).

        Example:
            ``auto-merge: merged 2, left 1 for manual resolution (alc/tick-abc)``

        When nothing was left conflicting the parenthetical branch list is omitted.
        """
        line = (
            f"auto-merge: merged {len(self.merged)}, "
            f"left {len(self.conflicted)} for manual resolution"
        )
        if self.conflicted:
            line += f" ({', '.join(self.conflicted)})"
        return line


def _merge_message(repo_root: Path, branch: str) -> str:
    """Return the merge commit message for *branch*: its tip subject.

    The tip subject is already ``feat(auto): <title>`` (from the Part C exit-commit),
    so reusing it keeps a consistent history. Falls back to ``Merge <branch>`` when
    the subject can't be read (missing branch, git unavailable, etc.).
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "log", "-1", "--format=%s", branch],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return f"Merge {branch}"
    if result.returncode != 0:
        return f"Merge {branch}"
    subject = result.stdout.strip()
    return subject or f"Merge {branch}"


def auto_merge_branches(repo_root: Path, branches: list[str]) -> MergeReport:
    """Sequentially merge each demand *branch* into the current branch.

    Processes ``sorted(branches)`` (a stable, deterministic order — required so the
    merge history is reproducible). For each branch:

    - ``git -C <root> merge --no-ff <branch> -m <subject>`` where ``<subject>`` is the
      branch tip's own subject (``feat(auto): <title>``). ``--no-ff`` forces a real
      merge commit even when a fast-forward is possible (consistent history).
      - returncode 0 -> clean merge: ``git branch -d <branch>`` (delete the now-merged
        branch), append to ``merged``.
      - returncode != 0 -> conflict (or any merge failure): ``git merge --abort``
        (best-effort), LEAVE the branch, append to ``conflicted``, continue the loop.

    Merges are serialized by construction (this runs post-batch, single-threaded), so
    no git-mutation lock is needed here.

    Never raises: a missing ``git`` (FileNotFoundError) degrades gracefully — a
    ``[merge] git not found; ...`` warning is printed to stderr and whatever was
    accumulated so far is returned, with the remaining branches counted as conflicted
    (nothing could be merged), so no branch is silently lost.

    Precondition: the current branch's working tree must be mergeable. Demand branches
    EXCLUDE ``.alc/`` (Part C), so uncommitted ``.alc/`` queue state on main does NOT
    block these merges (git only refuses when a merge would overwrite locally-modified
    paths, and the branches never touch ``.alc/``). This helper adds no dirty-tree
    guard — the drain (Part E) owns the merge context.
    """
    report = MergeReport()
    ordered = sorted(branches)

    for i, branch in enumerate(ordered):
        message = _merge_message(repo_root, branch)
        try:
            merge = subprocess.run(
                ["git", "-C", str(repo_root), "merge", "--no-ff", branch, "-m", message],
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            # git not installed — never raise out of the auto-merge pass. Whatever
            # could not be merged is recorded as conflicted so no branch is lost.
            print(
                "[merge] git not found; skipping auto-merge of remaining branches.",
                file=sys.stderr,
            )
            report.conflicted.extend(ordered[i:])
            return report

        if merge.returncode == 0:
            # Clean merge: delete the now-merged branch (-d refuses an unmerged one).
            subprocess.run(
                ["git", "-C", str(repo_root), "branch", "-d", branch],
                capture_output=True,
            )
            report.merged.append(branch)
        else:
            # Conflict (or any merge failure): abort so no MERGE_HEAD is left behind,
            # leave the branch intact, and continue with the rest.
            subprocess.run(
                ["git", "-C", str(repo_root), "merge", "--abort"],
                capture_output=True,
            )
            report.conflicted.append(branch)

    return report
