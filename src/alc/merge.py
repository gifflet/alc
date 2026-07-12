# merge.py — Post-batch integration of the passed demand branches into the current branch.
# After a drain wave, each SUCCESSFUL demand's branch (alc/tick-<hex>, produced by the
# worktree exit-commit) is replayed onto the current branch, LINEARLY. A clean integration
# deletes the branch; a conflict LEAVES it for the operator to resolve — never a silent clobber.
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MergeReport:
    """Outcome of an auto-merge pass over a set of demand branches.

    Attributes:
        merged: Branches integrated into the current branch, then deleted (sorted order).
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


def auto_merge_branches(repo_root: Path, branches: list[str]) -> MergeReport:
    """Integrate each demand *branch* into the current branch LINEARLY (cherry-pick).

    Processes ``sorted(branches)``. For each branch, cherry-picks the commits it holds
    that the current branch (``HEAD``) does not yet have — replaying the demand's own
    ``feat(auto): <title>`` commit(s) onto the tip. This keeps history LINEAR: one commit
    per demand, its OWN message, and NO merge commit — so a demand never shows up twice
    (the old ``--no-ff`` merge created a merge commit that reused the subject, which read
    like a duplicate).

    - A clean cherry-pick deletes the (now-redundant) branch and records it as merged.
    - A conflict runs ``git cherry-pick --abort`` and LEAVES the branch, recording it as
      conflicted — never a silent clobber.
    - A branch already contained in the current branch (nothing to replay) is just dropped.

    Integrations are serialized by construction (this runs post-batch/-wave, single-threaded),
    so no git-mutation lock is needed here.

    Never raises: a missing ``git`` degrades gracefully — the remaining branches are recorded
    as conflicted (nothing could be integrated), so no branch is silently lost.

    Precondition: the current branch's working tree must be replayable. Demand branches
    EXCLUDE ``.alc/`` (Part C), so uncommitted ``.alc/`` queue state on the current branch does
    NOT block the cherry-pick. This helper adds no dirty-tree guard — the drain owns the context.
    """
    report = MergeReport()
    ordered = sorted(branches)

    for i, branch in enumerate(ordered):
        try:
            # Commits this branch holds that the current branch lacks, oldest-first so
            # cherry-pick replays them in order (usually one: the worktree exit-commit).
            rev = subprocess.run(
                ["git", "-C", str(repo_root), "rev-list", "--reverse", f"HEAD..{branch}"],
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            print(
                "[merge] git not found; skipping auto-merge of remaining branches.",
                file=sys.stderr,
            )
            report.conflicted.extend(ordered[i:])
            return report

        if rev.returncode != 0:
            # The branch can't be read (missing/ambiguous ref) — leave it, don't crash.
            report.conflicted.append(branch)
            continue

        commits = rev.stdout.split()
        if not commits:
            # Already contained in the current branch — nothing to replay; drop the branch.
            subprocess.run(
                ["git", "-C", str(repo_root), "branch", "-D", branch], capture_output=True
            )
            report.merged.append(branch)
            continue

        cherry = subprocess.run(
            ["git", "-C", str(repo_root), "cherry-pick", *commits],
            capture_output=True,
            text=True,
        )
        if cherry.returncode == 0:
            # Cherry-pick creates NEW commits, so the branch is not "merged" in git's eyes;
            # -D force-deletes the now-redundant branch (its work is on the current branch).
            subprocess.run(
                ["git", "-C", str(repo_root), "branch", "-D", branch], capture_output=True
            )
            report.merged.append(branch)
        else:
            # Conflict: abort so no CHERRY_PICK_HEAD lingers, then leave the branch intact.
            subprocess.run(
                ["git", "-C", str(repo_root), "cherry-pick", "--abort"], capture_output=True
            )
            report.conflicted.append(branch)

    return report
