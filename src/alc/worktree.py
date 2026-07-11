# worktree.py — Opt-in worktree isolation for alc run / alc flow.
# Wraps `git worktree` to run a mandate inside a temporary branch so the
# agent's file edits are contained there instead of mutating the operator's
# working tree.
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from pathlib import Path

from alc.models import ProvisionSpec

# Serialises every git mutation (worktree add/remove, branch -D). `git worktree
# add`/`remove` are not concurrency-safe on a single repo, so concurrent fan-out
# holds this lock for the whole of __enter__ and the whole of __exit__. The engine
# turn between enter and exit runs OUTSIDE the lock, so units still run in parallel.
_GIT_MUTATION_LOCK = threading.Lock()


def is_git_repo(path: Path) -> bool:
    """Return True if *path* is inside a git work tree."""
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def git_toplevel(path: Path) -> Path:
    """Return the absolute path to the repository root that contains *path*."""
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(result.stdout.strip())


class IsolatedWorktree:
    """Context manager that runs a mandate inside a temporary git worktree.

    Creates a new branch from the current HEAD, checks it out into a temp
    directory, and on exit either commits any changes made there (leaving the
    branch intact for review) or cleans everything up if the agent wrote nothing.

    Attributes:
        branch: The temporary branch name (``alc/<label>-<hex8>``).
        path: The filesystem path of the worktree temp directory.
        committed: True after exit if changes were staged and committed.
    """

    def __init__(
        self, repo_root: Path, label: str, commit_message: str = "alc: {branch}"
    ) -> None:
        self._repo_root = repo_root
        self.branch: str = f"alc/{label}-{uuid.uuid4().hex[:8]}"
        self.path: Path = Path(tempfile.mkdtemp(prefix="alc-wt-"))
        self.committed: bool = False
        # Exit-commit message template with a `{branch}` placeholder. Defaults to
        # the former hardcoded value so an unset manifest is byte-identical.
        self._commit_message = commit_message

    def __enter__(self) -> Path:
        """Create the worktree and return the directory path.

        Held under ``_GIT_MUTATION_LOCK`` so concurrent fan-out never runs two
        ``git worktree add`` on the same repo at once.
        """
        with _GIT_MUTATION_LOCK:
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self._repo_root),
                    "worktree",
                    "add",
                    str(self.path),
                    "-b",
                    self.branch,
                ],
                capture_output=True,
                text=True,
            )
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to create git worktree for branch '{self.branch}':\n"
                f"{result.stderr.strip()}"
            )
        return self.path

    def __exit__(self, *exc) -> None:
        """Commit any changes in the worktree, then remove it.

        If the agent made changes, they are committed on ``self.branch`` and
        the worktree is removed (the branch retains the commit for review).

        If no changes were made, the worktree and the empty branch are both
        deleted, and ``self.committed`` is left False.

        Exceptions from the body are never suppressed.

        The entire add/diff/commit/remove/branch mutation sequence is held under
        ``_GIT_MUTATION_LOCK`` so concurrent fan-out never runs two ``git worktree
        remove`` on the same repo at once.
        """
        with _GIT_MUTATION_LOCK:
            try:
                # Stage everything the agent may have written.
                subprocess.run(
                    ["git", "-C", str(self.path), "add", "-A"],
                    capture_output=True,
                )

                # Detect whether there is anything staged.
                diff = subprocess.run(
                    ["git", "-C", str(self.path), "diff", "--cached", "--quiet"],
                    capture_output=True,
                )
                has_changes = diff.returncode == 1  # returncode 1 => differences exist

                if has_changes:
                    # Render the template; a bad operator template must not crash
                    # the exit-commit — fall back to the built-in default.
                    try:
                        message = self._commit_message.format(branch=self.branch)
                    except (KeyError, IndexError, ValueError):
                        message = f"alc: {self.branch}"
                    subprocess.run(
                        [
                            "git",
                            "-C",
                            str(self.path),
                            "commit",
                            "-m",
                            message,
                        ],
                        capture_output=True,
                        check=True,
                    )
                    self.committed = True

                # Remove the worktree (--force handles the unmerged-branch case).
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(self._repo_root),
                        "worktree",
                        "remove",
                        "--force",
                        str(self.path),
                    ],
                    capture_output=True,
                )

                if not has_changes:
                    # Nothing was written — delete the empty branch too.
                    subprocess.run(
                        [
                            "git",
                            "-C",
                            str(self._repo_root),
                            "branch",
                            "-D",
                            self.branch,
                        ],
                        capture_output=True,
                    )
            except Exception:
                # Attempt best-effort cleanup even if something above failed, then
                # re-raise so the caller knows something went wrong.
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(self._repo_root),
                        "worktree",
                        "remove",
                        "--force",
                        str(self.path),
                    ],
                    capture_output=True,
                )
                raise
        # Return None (falsy) — do not suppress exceptions from the body.


def _deep_copy(src: Path, dst: Path) -> None:
    """Deep-copy *src* to *dst* — a directory tree (symlinks preserved) or a file."""
    if src.is_dir():
        shutil.copytree(src, dst, symlinks=True)
    else:
        shutil.copy2(src, dst)


def _cow_copy(src: Path, dst: Path) -> None:
    """Copy-on-write clone *src* to *dst*, falling back to a deep copy.

    Uses ``cp -c`` on macOS (APFS) and ``cp --reflink=auto`` on Linux. When the
    filesystem lacks COW support the ``cp`` exits non-zero (or ``cp`` is missing
    and raises); either way we fall back to a plain deep copy so the result is
    always an ISOLATED copy — never a raise on COW-unsupported.
    """
    if sys.platform == "darwin":
        cmd = ["cp", "-c", "-R", str(src), str(dst)]
    else:
        cmd = ["cp", "--reflink=auto", "-R", str(src), str(dst)]
    try:
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode == 0:
            return
    except Exception:
        pass  # cp missing / unusable -> fall through to the deep copy
    # COW unsupported or cp failed: a partial dst may exist from a failed cp.
    if dst.exists():
        if dst.is_dir() and not dst.is_symlink():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    _deep_copy(src, dst)


def provision_worktree(
    worktree: Path, project_root: Path, provisions: list[ProvisionSpec]
) -> None:
    """Provision gitignored runtime deps from *project_root* into *worktree*.

    For each spec, ``src = project_root / spec.path`` and ``dst = worktree /
    spec.path``. A missing source is skipped (nothing to provision). Any existing
    ``dst`` (a worktree may carry a tracked placeholder) is removed first, then:
      - ``link``  -> symlink ``src`` into the worktree (SHARED — read-only-safe only).
      - ``copy``  -> an isolated deep copy.
      - ``clone`` -> a copy-on-write clone, falling back to a deep copy.

    Handles both a directory (node_modules, data) and a single file (.env). With
    an empty *provisions* list this loops zero times, so a worktree run is
    byte-identical to today's behavior. Pure helper — no git access needed.
    """
    for spec in provisions:
        src = project_root / spec.path
        if not src.exists():
            continue  # nothing to provision for this path
        dst = worktree / spec.path
        dst.parent.mkdir(parents=True, exist_ok=True)
        # Remove any existing dst (e.g. a tracked placeholder) so the provision
        # is deterministic regardless of what the worktree checked out.
        if dst.exists() or dst.is_symlink():
            if dst.is_dir() and not dst.is_symlink():
                shutil.rmtree(dst)
            else:
                dst.unlink()

        if spec.kind == "link":
            os.symlink(src, dst)
        elif spec.kind == "copy":
            _deep_copy(src, dst)
        else:  # "clone"
            _cow_copy(src, dst)
