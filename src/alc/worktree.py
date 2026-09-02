# worktree.py — Opt-in worktree isolation for alc run / alc flow.
# Wraps `git worktree` to run a mandate inside a temporary branch so the
# agent's file edits are contained there instead of mutating the operator's
# working tree.
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

from alc.models import ProvisionSpec

# Serialises every git mutation (worktree add/remove, branch -D). `git worktree
# add`/`remove` are not concurrency-safe on a single repo, so concurrent fan-out
# holds this lock for the whole of __enter__ and the whole of __exit__. The engine
# turn between enter and exit runs OUTSIDE the lock, so units still run in parallel.
_GIT_MUTATION_LOCK = threading.Lock()

# Guards the allocated-port registry so concurrent worktree runs (the parallel
# drain) get DISJOINT port sets — an allocation still in flight cannot hand out a
# port another in-flight allocation already claimed.
_PORT_LOCK = threading.Lock()
_ALLOCATED_PORTS: set[int] = set()


def allocate_free_ports(n: int) -> list[int]:
    """Allocate *n* distinct free TCP ports, reserving them against concurrent runs.

    Under ``_PORT_LOCK``, repeatedly bind a socket to ``("", 0)`` (an OS-chosen
    free port), read its number, and keep it only when it is not already in
    ``_ALLOCATED_PORTS`` — so two allocations in flight at once return disjoint
    sets. Each socket is closed immediately: the port is passed as env and bound
    by the app, never held open by ALC (best-effort — a tiny race window is
    acceptable; the dev server fails-fast, surfaced by QA).

    The retry loop is bounded so a pathological run (every OS-chosen port already
    reserved) raises instead of spinning forever.
    """
    if n <= 0:
        return []
    ports: list[int] = []
    with _PORT_LOCK:
        attempts = 0
        max_attempts = n * 100  # generous bound; never expected to be hit
        while len(ports) < n:
            attempts += 1
            if attempts > max_attempts:
                # Atomic: never leave a partial reservation stuck in the registry.
                for p in ports:
                    _ALLOCATED_PORTS.discard(p)
                raise RuntimeError(
                    f"Could not allocate {n} free ports after {max_attempts} attempts."
                )
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("", 0))
                port = sock.getsockname()[1]
            if port in _ALLOCATED_PORTS:
                continue
            _ALLOCATED_PORTS.add(port)
            ports.append(port)
    return ports


def release_ports(ports: list[int]) -> None:
    """Release previously allocated ports back to the registry (best-effort)."""
    with _PORT_LOCK:
        for port in ports:
            _ALLOCATED_PORTS.discard(port)


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
        commit_on_exit: When True (default), ``__exit__`` commits any staged
            changes; when set False by the caller (before ``__exit__``) the exit
            commits nothing and discards the branch — the isolation owner (e.g. a
            failed committing demand) throws the worktree's work away.
    """

    def __init__(
        self,
        repo_root: Path,
        label: str,
        commit_message: str = "alc: {branch}",
        exclude_paths: tuple[str, ...] = (),
        message_provider: Callable[[str], str] | None = None,
        provisions: Sequence[ProvisionSpec] = (),
    ) -> None:
        self._repo_root = repo_root
        self.branch: str = f"alc/{label}-{uuid.uuid4().hex[:8]}"
        self.path: Path = Path(tempfile.mkdtemp(prefix="alc-wt-"))
        self.committed: bool = False
        # Exit-commit message template with a `{branch}` placeholder. Defaults to
        # the former hardcoded value so an unset manifest is byte-identical.
        self._commit_message = commit_message
        # Path prefixes to keep OUT of the exit-commit (mirrors commit_workdir's
        # `git reset -q -- <entry>` step). Default () -> no reset -> commits
        # everything incl. `.alc/` exactly as before (byte-identical).
        self._exclude_paths = exclude_paths
        # Optional callable (diff: str) -> str that generates the commit message
        # from the staged diff.  When None the static _commit_message is used.
        self._message_provider = message_provider
        # When False the exit commits nothing and deletes the branch, discarding
        # whatever the agent wrote. Settable by the caller after __enter__.
        self.commit_on_exit: bool = True
        # Gitignored runtime deps (node_modules/.env/data) provisioned INTO the
        # worktree at __enter__ — centralised here so EVERY isolated path provisions
        # identically. Default () -> no provisioning, byte-identical to a worktree
        # that carries only tracked files.
        self._provisions = provisions

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
        # Provision gitignored runtime deps INTO the fresh worktree before returning
        # it — a git worktree checks out only TRACKED files, so a gitignored dep like
        # node_modules is absent and a check such as tsc/eslint/vitest would exit 127.
        # Doing it here means every isolated path (run/flow --isolate, fan-out, queue)
        # provisions identically. An empty list is a no-op (skipped entirely).
        if self._provisions:
            try:
                provision_worktree(self.path, self._repo_root, list(self._provisions))
            except Exception:
                # Never leak the just-created worktree if provisioning fails — remove
                # it under the lock (mirrors __exit__'s best-effort cleanup), re-raise.
                with _GIT_MUTATION_LOCK:
                    subprocess.run(
                        ["git", "-C", str(self._repo_root), "worktree", "remove",
                         "--force", str(self.path)],
                        capture_output=True,
                    )
                raise
        # One line of prevention where the failure would otherwise be cryptic.
        # A gitignored dep dir (node_modules) that exists in the main tree but
        # not in this worktree means every check that needs it will fail with
        # the TOOL's error — npx fetching a stray `tsc` package, ESM
        # resolution walls — and nothing connects that to its cause. Dogfood
        # finding 3: the engine then burns repair turns on an environment
        # problem it can never fix. Advisory only; the run proceeds unchanged.
        for gap in unprovisioned_dep_dirs(self.path, self._repo_root):
            print(
                f"[hint] {gap}/node_modules exists in your project but is "
                "gitignored and was not provisioned into this worktree — checks "
                f"that run in {gap}/ will likely fail. Add it to "
                "`worktree_provision` in .alc/manifest.yaml.",
                file=sys.stderr,
            )
        return self.path

    def __exit__(self, *exc) -> None:
        """Commit any changes in the worktree, then remove it.

        If the agent made changes, they are committed on ``self.branch`` and
        the worktree is removed (the branch retains the commit for review).

        If no changes were made — or ``commit_on_exit`` was set False (the
        isolation owner is discarding the work, e.g. a failed committing demand)
        — the worktree and the branch are both deleted, and ``self.committed`` is
        left False.

        When ``_exclude_paths`` is non-empty, each entry is ``git reset -q --``
        unstaged after ``git add -A`` (mirroring commit_workdir's step 2) so those
        prefixes (e.g. ``.alc/``) never land in the exit-commit.

        Concurrency design: staging, diff capture, and message generation run
        OUTSIDE ``_GIT_MUTATION_LOCK`` — they operate on this worktree's isolated
        index and never touch the shared repo structure.  Only ``git commit``,
        ``git worktree remove``, and ``git branch -D`` (all of which mutate the
        shared repo) are held under the lock.  This lets concurrent fan-out units
        generate their commit messages (including an engine call) in parallel
        without serialising on the lock.

        Exceptions from the body are never suppressed.
        """
        # --- Phase 1: stage, diff-check, and message generation (lock-free) ---
        has_changes = False
        message = self._commit_message.replace("{branch}", self.branch)

        try:
            if not self.commit_on_exit:
                # The caller is discarding this worktree's work.
                has_changes = False
            else:
                # Stage everything the agent may have written.
                subprocess.run(
                    ["git", "-C", str(self.path), "add", "-A"],
                    capture_output=True,
                )

                # Unstage excluded prefixes (mirrors commit_workdir step 2)
                # so e.g. `.alc/` never lands in a demand's exit-commit.
                for entry in self._exclude_paths:
                    subprocess.run(
                        ["git", "-C", str(self.path), "reset", "-q", "--", entry],
                        capture_output=True,
                    )

                # Unstage the runtime deps ALC provisioned into this worktree — they
                # must NEVER land in the exit-commit. A project's `.gitignore` may not
                # match them: `node_modules/` (trailing slash = DIRECTORY) does NOT
                # ignore the `link:` SYMLINK, so `git add -A` would otherwise commit a
                # machine-specific absolute-path link.
                for spec in self._provisions:
                    subprocess.run(
                        ["git", "-C", str(self.path), "reset", "-q", "--", spec.path],
                        capture_output=True,
                    )

                # Detect whether there is anything staged.
                diff_check = subprocess.run(
                    ["git", "-C", str(self.path), "diff", "--cached", "--quiet"],
                    capture_output=True,
                )
                has_changes = diff_check.returncode == 1  # 1 => differences exist

                # An ABORTED unwind (Ctrl-C, the UI's Cancel, any exception) must
                # never wait on an engine call: the provider takes longer than the
                # UI cancel's 5s SIGTERM->SIGKILL grace, so the kill landed mid-
                # generation — no commit, a leaked worktree, and the engine's work
                # orphaned. That broke, on the UI path only, the promise D2 makes
                # everywhere: cancelling still commits your work to the branch. An
                # aborted run does not need an engine-authored commit message; it
                # needs the commit. The static template is instant.
                aborted = bool(exc) and exc[0] is not None
                if has_changes and self._message_provider is not None and not aborted:
                    try:
                        diff_text = subprocess.run(
                            ["git", "-C", str(self.path), "diff", "--cached"],
                            capture_output=True,
                            text=True,
                        ).stdout
                        message = self._message_provider(diff_text)
                    except Exception:
                        pass  # provider failure -> keep the template-rendered message
        except Exception as _stage_exc:
            # Stage phase failed: attempt best-effort cleanup under the lock and
            # re-raise so the caller knows something went wrong.
            with _GIT_MUTATION_LOCK:
                subprocess.run(
                    ["git", "-C", str(self._repo_root), "worktree", "remove",
                     "--force", str(self.path)],
                    capture_output=True,
                )
            raise

        # --- Phase 2: commit + worktree-remove + branch-delete (under lock) ---
        with _GIT_MUTATION_LOCK:
            try:
                if has_changes:
                    subprocess.run(
                        ["git", "-C", str(self.path), "commit", "-m", message],
                        capture_output=True,
                        check=True,
                    )
                    self.committed = True

                # Remove the worktree (--force handles the unmerged-branch case).
                subprocess.run(
                    ["git", "-C", str(self._repo_root), "worktree", "remove",
                     "--force", str(self.path)],
                    capture_output=True,
                )

                if not has_changes:
                    # Nothing was written — delete the empty branch too.
                    subprocess.run(
                        ["git", "-C", str(self._repo_root), "branch", "-D", self.branch],
                        capture_output=True,
                    )
            except Exception:
                # Best-effort cleanup: remove the worktree if still present,
                # then re-raise so the caller knows something went wrong.
                subprocess.run(
                    ["git", "-C", str(self._repo_root), "worktree", "remove",
                     "--force", str(self.path)],
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


def materialize_isolated(dst: Path) -> None:
    """Replace a symlinked provision with an isolated COW clone of its target, so a
    mutating refresh (e.g. npm install) can never write through the link into the
    operator's shared dependency dir.

    Only meaningful for a SYMLINK *dst* (a ``link:`` provision) — callers guard on
    that, and a non-symlink *dst* (an already-isolated ``copy:``/``clone:`` result,
    or an absent path) is left untouched. The symlink's target is resolved FIRST
    (before the link is removed), then the link is unlinked and the target COW-cloned
    into its place via the same clone-with-deep-copy fallback the ``copy:``/``clone:``
    strategies use. A dangling/missing target is handled gracefully: the link is
    removed and *dst* is left ABSENT so the install materializes it fresh — never a
    crash.
    """
    if not dst.is_symlink():
        return
    # Resolve the target while the link still exists (resolve() is non-strict, so a
    # dangling link yields a path that simply does not exist below).
    target = dst.resolve()
    # Remove the symlink itself — unlink never follows into the target.
    dst.unlink()
    if not target.exists():
        # Dangling/missing target: leave dst absent, let the install create it fresh.
        return
    _cow_copy(target, dst)


def unprovisioned_dep_dirs(worktree: Path, project_root: Path) -> list[str]:
    """Project-relative dirs whose node_modules exists in the main tree but not
    in *worktree* — the signature of a missing ``worktree_provision`` entry.

    Scans the root and one level down (mirroring ``detect_nested_stacks``'s
    depth), keyed on ``package.json`` being TRACKED so a stray directory never
    fires. Pure read; never raises.
    """
    gaps: list[str] = []
    try:
        candidates = [project_root, *sorted(d for d in project_root.iterdir() if d.is_dir())]
        for cand in candidates:
            if not (cand / "package.json").is_file():
                continue
            rel = cand.relative_to(project_root)
            if (cand / "node_modules").exists() and not (worktree / rel / "node_modules").exists():
                gaps.append(str(rel) if str(rel) != "." else ".")
    except OSError:
        return []
    return gaps


def runtime_provisions(manifest) -> list:
    """The manifest's declared provisions plus ALC's own runtime intake.

    `signals_dir` is gitignored runtime state — correct for the repo, fatal for
    an isolated run that needs to READ it: a worktree checks out only tracked
    files, so a signal-driven unit (the grower's listen specialist) ran
    "successfully" against an empty signal queue while the signals sat in the
    root (dogfood round 8, finding 39). Signals are provisioned as a COPY:
    cheap (small JSON files), isolated (a worktree consuming one cannot corrupt
    the root's), and read-only in spirit — archiving/consuming stays a
    root-side concern. An operator-declared provision for the same path wins
    (no duplicate). Accepts the Manifest loosely typed so this module keeps no
    intake import.
    """
    from alc.models import ProvisionSpec

    provisions = list(manifest.worktree_provision)
    covered = {spec.path for spec in provisions}
    if manifest.signals_dir not in covered:
        provisions.append(ProvisionSpec(copy=manifest.signals_dir))
    return provisions


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
