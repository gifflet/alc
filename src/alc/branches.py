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

# A single variant's diff can be large (a broad refactor touches many files).
# The Compare view and `alc compare --diff` both render it inline, so cap the
# payload: past this many characters the transport/render cost outweighs the
# value of one more hunk, and the reader is pointed at `git diff` for the rest.
_MAX_DIFF_CHARS = 200_000


@dataclass(frozen=True)
class AlcBranch:
    """One `alc/*` branch: its name, provenance label, and merge status."""

    name: str            # full branch name, e.g. "alc/tick-a1b2c3d4"
    label: str           # provenance segment, e.g. "run"/"flow"/"tick"/"conduct"
    committed_at: float  # epoch seconds of the branch tip's committer date
    merged: bool         # already contained in HEAD


@dataclass(frozen=True)
class BranchDiff:
    """The unified diff of one `alc/*` branch against its merge-base with a base ref."""

    text: str        # unified diff; "" when the branch changes nothing vs the merge-base
    truncated: bool  # True when `text` was cut to `max_chars` (more diff exists)


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


def live_variant_branches(repo_root: Path) -> set[str]:
    """Names of every `alc/variant-*` branch that still exists — ONE for-each-ref call.

    The Compare surface (bare `alc compare` / the UI view) reads back archived
    variants that can OUTLIVE their branch: an adopted or discarded variant leaves
    its archive on disk while its `alc/variant-*` ref is gone. Membership in this
    set is exactly "the branch is still there" — a variant NOT in it is resolved
    (Diff/Adopt would 404). One `for-each-ref` answers liveness for the WHOLE table
    (no per-branch cost), unlike `list_alc_branches`, whose per-branch merged check
    spends a `rev-list` each — liveness needs only the names.

    ``%(refname:short)`` yields the short name (e.g. `alc/variant-1-a1b2c3d4`) so
    it matches `variant_row`'s ``branch`` field byte-for-byte.

    Never raises, mirroring this module's contract: a missing ``git`` binary
    (``FileNotFoundError``) -> ``set()`` (with a house-style stderr note); a
    non-zero exit — not a git repository -> ``set()``.
    """
    try:
        result = subprocess.run(
            [
                "git", "-C", str(repo_root), "for-each-ref",
                "refs/heads/alc/variant-*", "--format=%(refname:short)",
            ],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print("[branches] git not found; no variant branches listed.", file=sys.stderr)
        return set()
    if result.returncode != 0:
        return set()
    return {line for line in result.stdout.splitlines() if line.strip()}


def branch_diff(
    repo_root: Path, branch: str, base: str = "HEAD", max_chars: int = _MAX_DIFF_CHARS
) -> BranchDiff | None:
    """Return the unified diff of *branch* against its merge-base with *base*.

    Uses the THREE-dot form ``git diff <base>...<branch>``: git diffs *branch*
    against the merge-base of the two refs, so the result shows ONLY the
    branch's own changes even after *base* has advanced past the branch point —
    the base's later, unrelated commits never bleed into a variant's diff. This
    is the same reachability the operator's ``delivery.changed_files`` relies on.

    Read-only by construction: ``--no-ext-diff`` blocks any user-configured
    external diff tool from running, ``--no-color`` keeps the bytes clean for
    the transport/render layers, and the trailing ``--`` disambiguates the ref
    from any path of the same name. Nothing here mutates the repository.

    Never raises, mirroring this module's contract:
      * a missing ``git`` binary (``FileNotFoundError``) -> ``None``;
      * a non-zero exit — an unknown or ambiguous *branch*/*base* ref -> ``None``.
    ``None`` therefore means "no diff is computable" (the branch is gone —
    already adopted or discarded). A branch that exists but adds nothing over
    the merge-base yields ``BranchDiff("", False)``, a DISTINCT, well-defined
    "exists, empty diff" — never conflated with the missing-branch ``None``.

    Diffs past *max_chars* are truncated (``text[:max_chars]``, ``truncated``
    True) so one oversized variant can never bloat the response.
    """
    try:
        result = subprocess.run(
            [
                "git", "-C", str(repo_root), "diff", "--no-color", "--no-ext-diff",
                f"{base}...{branch}", "--",
            ],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print("[branches] git not found; no diff available.", file=sys.stderr)
        return None
    if result.returncode != 0:
        # Ref can't be read (missing/ambiguous) — degrade to "no diff computable".
        return None
    text = result.stdout
    if len(text) > max_chars:
        return BranchDiff(text[:max_chars], True)
    return BranchDiff(text, False)


def _worktrees_by_branch(repo_root: Path) -> dict[str, Path]:
    """Map each branch checked out in a worktree to that worktree's path.

    Parses ``git worktree list --porcelain``. Used to find the ISOLATED worktree
    holding an `alc/*` run branch so `delete_branches` can force-remove an orphaned
    one (left by an interrupted run) before deleting the branch. Never raises: a
    missing ``git`` binary or a non-zero exit yields an empty map.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return {}
    if result.returncode != 0:
        return {}
    mapping: dict[str, Path] = {}
    current_path: Path | None = None
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            current_path = Path(line[len("worktree "):])
        elif line.startswith("branch ") and current_path is not None:
            ref = line[len("branch "):].strip()
            name = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
            mapping[name] = current_path
    return mapping


def run_report_filename(branch: str) -> str:
    """The archived-report filename a direct isolated `alc run` writes for *branch*.

    An isolated run names its `*.report.json` after the branch (slashes → dashes)
    so `alc discard` can find and delete it when the branch is discarded — otherwise
    a rejected run's report would linger and keep inflating audit / Mix Health, a
    real drift on a long-lived project. The single source of truth for the name,
    shared by the archiver (`cli._archive_run_report`) and the remover here.
    """
    return branch.replace("/", "-") + ".report.json"


def branch_verified(runs_dir: Path, branch: str, label: str) -> bool | None:
    """Did the run behind *branch* pass its checks? None when unknowable.

    An isolated `alc run` archives `<branch>.report.json` only when the report
    succeeded, and a spike never commits a branch — so for a `run` branch the
    report is present exactly when the run passed, and absent when it failed or
    was interrupted yet still committed. That last case is the one worth naming:
    a branch indistinguishable from verified work.

    A queue drain archives the same branch-named report for a successful `tick`
    branch (dogfood finding 9: both tasks of the first unattended run passed
    every check and the Inbox could only shrug None — the run KNEW), so `tick`
    joins `run` under the same test. A tick branch from BEFORE the drain wrote
    reports reads False ("review before landing"): conservative, and the only
    honest direction available. `flow` and `fanout-*` still archive nothing and
    stay None — no claim; a false alarm on every fan-out would be worse than
    the silence.

    Pure on purpose: callers resolve `runs_dir` themselves, so this stays free of
    manifest loading and usable from both the CLI and the web service.
    """
    if label not in ("run", "tick"):
        return None
    return (runs_dir / run_report_filename(branch)).exists()


def delete_branches(
    repo_root: Path, names: list[str], runs_dir: Path | None = None
) -> list[str]:
    """Force-delete each of *names* that is an `alc/` branch and not the current one.

    A ref outside the `alc/` prefix, or the currently checked-out branch, is
    silently skipped — never deleted. Returns the names actually deleted.

    When ``git branch -D`` fails because the branch is still checked out in an
    ISOLATED worktree — the state an INTERRUPTED run leaves (Ctrl-C, crash,
    timeout): a worktree with uncommitted changes holding the branch, which plain
    `git worktree prune` can't clear — that worktree is force-removed first (never
    the main worktree) and the delete retried, so `alc discard` (and the UI's
    discard, which shares this function) actually cleans up instead of reporting
    "Deleted 0 branches" and leaving the mess.

    When *runs_dir* is given, the archived report a direct isolated run wrote for a
    deleted branch (``runs/<branch-dashed>.report.json``) is removed too, so a
    discarded run stops counting in audit / Mix Health — no orphaned advisory data
    accumulating on a long-lived project. Never raises: a missing ``git`` binary
    yields an empty result.
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
    worktrees = _worktrees_by_branch(repo_root)

    def _branch_d(name: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(repo_root), "branch", "-D", name],
            capture_output=True,
            text=True,
        )

    deleted: list[str] = []
    for name in names:
        if not name.startswith("alc/") or name == current_branch:
            continue
        result = _branch_d(name)
        if result.returncode != 0 and name in worktrees:
            # The branch is held by an isolated worktree (an interrupted run).
            # Force-remove that worktree — but NEVER the main one — then retry.
            wt = worktrees[name]
            if wt.resolve() != repo_root.resolve():
                subprocess.run(
                    ["git", "-C", str(repo_root), "worktree", "remove", "--force", str(wt)],
                    capture_output=True,
                    text=True,
                )
                result = _branch_d(name)
        if result.returncode == 0:
            deleted.append(name)
            if runs_dir is not None:
                # Drop the discarded run's archived report so it stops counting.
                (runs_dir / run_report_filename(name)).unlink(missing_ok=True)
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
