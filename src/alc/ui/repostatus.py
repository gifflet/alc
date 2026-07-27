# repostatus.py — The UI's read model of a project's repo / working-tree status.
#
# This is the UI READ MODEL ONLY. The CLI preflight and the committing-Flow guard
# keep their own safety predicate, ``commit.has_non_alc_changes`` — this module
# must never replace it. What binds the two is agreement on ONE field: the
# ``dirty`` computed here is pinned equal to ``has_non_alc_changes`` by an
# agreement test (tests/ui/test_repostatus.py). Everything else here — branch,
# upstream, ahead/behind, untracked — is purely for surfacing the repo's shape in
# the UI (a live StatusBar cluster), never for gating a run.
#
# No-auto-fetch is load-bearing: ahead/behind come ONLY from the local
# remote-tracking ref (as of the operator's LAST fetch), read out of the single
# ``git status --porcelain=v2 --branch`` call. We NEVER run ``git fetch`` — not
# here, not anywhere in the watch path. A stale count is honest and cheap; a
# surprise network fetch on every keystroke is neither. The UI tooltip says as
# much ("as of your last fetch (ALC never fetches)").
from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

# The single source of truth for what "control-plane churn" looks like. A change
# confined to ``.alc/`` never counts as dirt — this mirrors
# ``commit.has_non_alc_changes``' own ``path.startswith(".alc/")`` rule, and is
# what the agreement test pins. Keeping v1 semantics: an untracked ``??``/``?``
# entry outside ``.alc/`` DOES count as dirty (git-add-all would sweep it).
_ALC_PREFIX = ".alc/"


def _outside_alc(path: str) -> bool:
    """True when *path* (repo-root-relative, forward slashes) is NOT under .alc/.

    A collapsed untracked directory arrives as ``.alc/`` (trailing slash) and is
    still correctly excluded. Porcelain WITHOUT ``-z`` C-quotes exotic paths,
    wrapping them in a leading double-quote (``"a\\tb"``); such a path fails the
    ``.alc/`` prefix and so is conservatively treated as OUTSIDE .alc/ — that can
    only ever over-report dirt, never falsely report a clean tree.
    """
    return not path.startswith(_ALC_PREFIX)


@dataclass(frozen=True)
class RepoStatus:
    """An immutable snapshot of a project's repo / working-tree status.

    Frozen on purpose: value equality is exactly the emit-on-change comparison
    the tracker uses (``old != new`` -> publish). ``ahead``/``behind`` are
    ``None`` when there is NO upstream (unknown), never ``0`` — a real ``0`` means
    "in sync with the tracking ref". ``available=False`` (the default) mirrors
    ``service.list_branches``' off-git pattern: no git, or not a repo, is a clean
    "nothing to show", never an error.
    """

    available: bool = False
    dirty: bool = False
    branch: str | None = None
    detached: bool = False
    upstream: str | None = None
    ahead: int | None = None
    behind: int | None = None
    untracked: int = 0


def parse_repo_status(porcelain_v2_text: str) -> RepoStatus:
    """Parse ``git status --porcelain=v2 --branch`` output into a RepoStatus.

    PURE: text in, RepoStatus out (always ``available=True`` — we only parse when
    git actually spoke). Understands the v2 grammar:

    * ``# branch.head <name|(detached)>`` — ``(detached)`` sets ``detached=True``
      and leaves ``branch=None``; any other value is the branch name (still set
      for an unborn ``(initial)`` branch).
    * ``# branch.upstream <ref>`` — the configured upstream.
    * ``# branch.ab +A -B`` — ahead/behind. Parsed INDEPENDENTLY of
      ``branch.upstream``: git omits this line when the tracking ref is gone even
      though an upstream is configured, so coupling them would wrongly zero the
      counts.
    * Change entries — ordinary ``1``, rename/copy ``2``, unmerged ``u`` — and
      untracked ``?``. A ``2`` line lists the TARGET path first, then ``\\t<orig>``;
      the target is what decides. ``!`` (ignored) is skipped defensively (it only
      appears with ``--ignored``, which we never pass).

    ``dirty`` is True iff any ``1``/``2``/``u``/``?`` entry's path is OUTSIDE
    ``.alc/``; ``untracked`` counts the ``?`` entries outside ``.alc/``.
    """
    branch: str | None = None
    detached = False
    upstream: str | None = None
    ahead: int | None = None
    behind: int | None = None
    dirty = False
    untracked = 0

    for line in porcelain_v2_text.splitlines():
        if not line:
            continue

        if line.startswith("# "):
            # Header lines carry the branch/upstream/ahead-behind metadata.
            if line.startswith("# branch.head "):
                value = line[len("# branch.head ") :].strip()
                if value == "(detached)":
                    detached = True
                else:
                    branch = value
            elif line.startswith("# branch.upstream "):
                upstream = line[len("# branch.upstream ") :].strip()
            elif line.startswith("# branch.ab "):
                # "+A -B" — read each half independently; a malformed token just
                # leaves that half as None (unknown), never crashes the parse.
                for token in line[len("# branch.ab ") :].split():
                    try:
                        if token.startswith("+"):
                            ahead = int(token[1:])
                        elif token.startswith("-"):
                            behind = int(token[1:])
                    except ValueError:
                        pass
            continue

        marker = line[0]
        path: str | None = None
        if marker == "1":
            # "1 <XY> <sub> <mH> <mI> <mW> <hH> <hI> <path>" — 8 fixed fields then
            # the path; maxsplit keeps a path with spaces intact.
            parts = line.split(" ", 8)
            if len(parts) == 9:
                path = parts[8]
        elif marker == "2":
            # "2 ...9 fields... <path>\t<orig>" — the TARGET path comes first.
            parts = line.split(" ", 9)
            if len(parts) == 10:
                path = parts[9].split("\t", 1)[0]
        elif marker == "u":
            # "u <XY> <sub> <m1> <m2> <m3> <mW> <h1> <h2> <h3> <path>" — 10 fields.
            parts = line.split(" ", 10)
            if len(parts) == 11:
                path = parts[10]
        elif marker == "?":
            # "? <path>" — an untracked entry (or a collapsed "? .alc/" dir).
            parts = line.split(" ", 1)
            if len(parts) == 2:
                path = parts[1]
        else:
            # "!" ignored, or anything unexpected — never counts toward dirt.
            continue

        if path is None or not _outside_alc(path):
            continue
        dirty = True
        if marker == "?":
            untracked += 1

    return RepoStatus(
        available=True,
        dirty=dirty,
        branch=branch,
        detached=detached,
        upstream=upstream,
        ahead=ahead,
        behind=behind,
        untracked=untracked,
    )


def repo_status(root: Path) -> RepoStatus:
    """Read *root*'s repo status via one ``git status --porcelain=v2 --branch``.

    A thin runner over ``parse_repo_status`` — same subprocess style as commit.py.
    Degrades exactly like ``commit.has_non_alc_changes``: ``FileNotFoundError``
    (no ``git`` binary) or a non-zero return (not a repo, or git < 2.11 which
    predates ``--porcelain=v2``) yields ``RepoStatus(available=False)``. NEVER
    raises, and NEVER fetches — the ahead/behind it reports are whatever the local
    tracking ref says as of the operator's last fetch.

    This is the UI read model. The CLI/flow safety predicate stays
    ``has_non_alc_changes``; an agreement test pins ``repo_status(root).dirty``
    equal to it so the two can never disagree on "dirty".
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain=v2", "--branch"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return RepoStatus(available=False)
    if result.returncode != 0:
        return RepoStatus(available=False)
    return parse_repo_status(result.stdout)


class RepoStatusTracker:
    """Debounce working-tree events, recompute status, and emit only on a flip.

    A composition collaborator of the Watcher — this keeps the debounce /
    recompute / emit-on-change responsibility OUT of the file-system plumbing.
    The Watcher's ``mark`` calls are cheap; the (potentially non-trivial) ``git
    status`` runs at most once per project per debounce window.

    * ``mark`` anchors a pending window on the FIRST event of a burst
      (``setdefault``): that bounds both latency (the status is read within one
      debounce window of the first change) AND cost (a burst of 500 saves is one
      recompute, not 500).
    * ``flush`` is called on every watch-loop tick; a pending project is
      recomputed once its window has elapsed, and ``worktree_changed`` is
      published ONLY when the new status differs from the last one seen (frozen
      value equality). The first computation is a cache miss and publishes once —
      harmless, it just seeds the UI.
    * ``prune`` drops state for projects the registry no longer lists.
    """

    def __init__(
        self,
        bus: object,
        read_status: Callable[[Path], RepoStatus] = repo_status,
        debounce_s: float = 0.4,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._bus = bus
        self._read_status = read_status
        self._debounce_s = debounce_s
        self._now = now
        # pid -> monotonic timestamp of the FIRST mark in the current window.
        self._pending: dict[str, float] = {}
        # pid -> the last RepoStatus published (the emit-on-flip baseline).
        self._last: dict[str, RepoStatus] = {}

    def mark(self, project_id: str) -> None:
        """Note that *project_id* saw a working-tree change (anchor the window)."""
        # setdefault: only the FIRST event of a burst sets the anchor time, so the
        # window is a throttle, not a per-event reset (which could starve forever
        # under a steady stream of saves).
        self._pending.setdefault(project_id, self._now())

    def flush(self, roots: dict[str, Path]) -> None:
        """Recompute + maybe publish for every pending project whose window elapsed.

        *roots* maps project_id -> repo root. Called every watch-loop tick, so it
        doubles as the debounce timer — no separate task. Never raises into the
        loop: ``read_status`` (``repo_status``) already degrades to available=False
        rather than throwing.
        """
        now = self._now()
        for pid in list(self._pending):
            if now - self._pending[pid] < self._debounce_s:
                continue  # window not elapsed yet — leave it pending
            self._pending.pop(pid, None)
            root = roots.get(pid)
            if root is None:
                # The project vanished between mark and flush — nothing to read.
                continue
            status = self._read_status(root)
            previous = self._last.get(pid)
            self._last[pid] = status
            if status != previous:
                # Emit-on-flip: publish only when the status actually changed.
                # A first-time (cache-miss) publish is intentional and harmless.
                self._bus.publish(
                    {
                        "type": "worktree_changed",
                        "project_id": pid,
                        "status": asdict(status),
                    }
                )

    def prune(self, live_ids: set[str]) -> None:
        """Drop pending/last state for projects no longer in the registry."""
        for pid in list(self._pending):
            if pid not in live_ids:
                self._pending.pop(pid, None)
        for pid in list(self._last):
            if pid not in live_ids:
                self._last.pop(pid, None)
