# watch.py — Watch each registered project and publish changes to the bus.
#
# Two concerns, split for testability:
#   * classify_change() and is_repo_watch_path() are PURE functions (path -> …)
#     so both are unit-tested without watchfiles.
#   * Watcher wraps watchfiles.awatch over the union of the registered projects'
#     repo ROOTS. The root (recursive) covers the working tree, ``.alc/`` and —
#     normally — ``.git/``; a monorepo subdir project ALSO watches the shared
#     ``<toplevel>/.git``. For run logs it keeps a per-file line offset and
#     publishes only the NEW lines as ``run_event`` messages. For everything
#     outside ``.alc/`` it defers to a RepoStatusTracker, which debounces the
#     churn into at most one ``git status`` per project per window and publishes a
#     ``worktree_changed`` only when the status actually flips.
#
# Filtering caveat: watchfiles filters PYTHON-side — the Rust watcher still walks
# the whole tree recursively, so ``is_repo_watch_path`` only trims what reaches
# our handler, it does NOT reduce the number of native watches. On Linux that
# means the usual inotify watch-count limits still apply to a large tree.
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from alc.ui.bus import EventBus
from alc.ui.registry import ProjectRegistry
from alc.ui.repostatus import RepoStatusTracker, repo_status

# Directories whose contents are never a repo-status signal — a pragmatic ignore
# set (build output, dependency trees, tool caches). Honoring the full
# ``.gitignore`` is deliberately OUT of scope: a stray unignored path only costs
# one debounced ``git status`` (which reports the truth anyway), never a wrong
# answer, so the cost of being approximate here is a single cheap recompute.
_IGNORE_DIRS = frozenset(
    {
        "node_modules",
        "dist",
        "build",
        "out",
        ".venv",
        "venv",
        "__pycache__",
        ".next",
        "target",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".idea",
        "coverage",
    }
)

# The ONLY ``.git/`` entries worth waking the status reader for. A commit always
# touches ``index`` plus a ref, a checkout moves ``HEAD``, a merge writes
# ``MERGE_HEAD`` — so watching these (plus anything under ``refs/``) catches every
# commit/branch/checkout without drowning in ``objects/``, ``logs/`` and hooks.
_GIT_WATCH_FILES = frozenset(
    {"HEAD", "ORIG_HEAD", "MERGE_HEAD", "FETCH_HEAD", "index", "packed-refs"}
)


def _strip_loop_suffix(name: str) -> str:
    """Return the loop name from a loops/ filename (state/ledger/def)."""
    for suffix in (".state.json", ".ledger.jsonl", ".yaml"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def is_repo_watch_path(path_str: str) -> bool:
    """Decide whether a changed path is worth handling (the awatch filter).

    * Under a ``.git/`` directory: allow ONLY the handful of refs/heads a commit,
      checkout or merge actually moves — the suffix after the LAST ``/.git/`` is
      one of ``_GIT_WATCH_FILES`` or starts with ``refs/`` — and NEVER a ``.lock``
      file. Dropping ``.lock`` halves the churn: git writes ``index.lock`` then
      renames it to ``index``, and the rename to the final name still fires an
      event, so nothing is lost. Everything else under ``.git/`` (``objects/``,
      ``logs/``, ``hooks/``, …) is rejected.
    * Otherwise: reject if ANY path component is in the pragmatic ignore set (and
      skip macOS ``.DS_Store`` noise); allow the rest. ``.alc/…`` paths are always
      allowed — the existing control-plane message stream must never be filtered.
    """
    marker = "/.git/"
    idx = path_str.rfind(marker)
    if idx != -1:
        suffix = path_str[idx + len(marker) :]
        if suffix.endswith(".lock"):
            return False
        return suffix in _GIT_WATCH_FILES or suffix.startswith("refs/")

    parts = path_str.split("/")
    if parts and parts[-1] == ".DS_Store":
        return False
    return not any(part in _IGNORE_DIRS for part in parts)


def classify_change(alc_dir: Path, changed: Path) -> dict | None:
    """Map a changed path under ``alc_dir`` to a bus message (without project_id).

    Returns None for paths the UI does not surface. Run logs return
    ``{"type": "run", "stem": ...}`` — the caller tails the file for the actual
    ``run_event`` lines rather than emitting one message per file write.
    """
    try:
        rel = changed.resolve().relative_to(alc_dir.resolve())
    except ValueError:
        return None
    parts = rel.parts
    if not parts:
        return None
    top = parts[0]

    if top == "runs" and changed.suffix == ".jsonl":
        return {"type": "run", "stem": changed.stem}

    if top == "queue":
        if "done" in parts and changed.name.endswith(".report.json"):
            return {"type": "report_added", "stem": changed.name[: -len(".report.json")]}
        return {"type": "queue_changed"}

    if top == "loops":
        return {"type": "loop_changed", "name": _strip_loop_suffix(changed.name)}

    if top == "signals":
        return {"type": "signals_changed"}

    if rel.name == "manifest.yaml" and len(parts) == 1:
        return {"type": "config_changed", "resource": "manifest"}

    if top in ("blueprints", "flows", "specialists", "primers", "prompts"):
        return {"type": "config_changed", "resource": top}

    if top == "ui" and rel.name == "run-configs.json":
        return {"type": "run_configs_changed"}

    return None


def _git_toplevel(root: Path) -> Path | None:
    """Return the git toplevel for *root*, or None if not in a repo / no git.

    Non-raising by design — mirrors commit.py's own toplevel resolution. We must
    NOT use the ``check=True`` variant (worktree.git_toplevel): a project that is
    not a git repo is a normal, silent case here, not an exception.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def _external_git(root: Path) -> Path | None:
    """Return ``<toplevel>/.git`` when it lies OUTSIDE *root*, else None.

    For a normal project (root == git toplevel) the ``.git`` dir is already under
    the watched root, so there is nothing extra to watch. For a monorepo subdir
    project the shared ``.git`` lives above the root and must be watched
    explicitly, or commits/branch moves would be invisible. Off-git projects
    return None (just watch the root).
    """
    toplevel = _git_toplevel(root)
    if toplevel is None:
        return None
    try:
        if toplevel.resolve() == root.resolve():
            return None
    except OSError:
        return None
    return toplevel / ".git"


class Watcher:
    """Async file watcher fanning project changes out to the EventBus."""

    def __init__(
        self,
        registry: ProjectRegistry,
        bus: EventBus,
        poll_ms: int = 400,
        status_reader=repo_status,
    ) -> None:
        self._registry = registry
        self._bus = bus
        self._poll_ms = poll_ms
        self._task: asyncio.Task | None = None
        self._stopped = False
        self._refresh = False
        self._offsets: dict[Path, int] = {}
        # The debounce/recompute/emit-on-flip collaborator. Its default 0.4s
        # window matches the 400ms poll tick, so the loop's own cadence IS the
        # debounce clock — no extra task. ``status_reader`` is injectable for tests.
        self._tracker = RepoStatusTracker(bus, read_status=status_reader)

    def start(self) -> None:
        """Launch the watch loop as a background asyncio task."""
        self._stopped = False
        self._task = asyncio.ensure_future(self._run())

    def stop(self) -> None:
        """Signal the watch loop to stop and cancel its task."""
        self._stopped = True
        if self._task is not None:
            self._task.cancel()

    def refresh(self) -> None:
        """Re-read the registry on the next loop iteration (project added/removed)."""
        self._refresh = True

    def _scan(self) -> tuple[dict[Path, str], dict[Path, str], dict[str, Path]]:
        """Scan the registry into the structures the watch loop needs.

        Returns ``(watch_paths, alc_map, roots)``:
          * ``watch_paths`` — ``{resolved path: pid}`` passed to awatch: each
            project ROOT plus a monorepo's external ``<toplevel>/.git``. Doubles as
            ``_handle``'s root-membership map for tracker marking.
          * ``alc_map`` — ``{resolved .alc dir: pid}`` for the existing message
            stream (``_handle`` resolves this FIRST, unchanged).
          * ``roots`` — ``{pid: root}`` for the tracker's status recompute.
        """
        watch_paths: dict[Path, str] = {}
        alc_map: dict[Path, str] = {}
        roots: dict[str, Path] = {}
        for project in self._registry.list():
            root = Path(project.path)
            if not root.is_dir():
                continue
            pid = project.id
            roots[pid] = root
            watch_paths[root.resolve()] = pid
            alc_dir = root / ".alc"
            if alc_dir.is_dir():
                alc_map[alc_dir.resolve()] = pid
            external_git = _external_git(root)
            if external_git is not None and external_git.is_dir():
                watch_paths[external_git.resolve()] = pid
        return watch_paths, alc_map, roots

    async def _run(self) -> None:
        """Watch the current project set, restarting when the registry changes."""
        from watchfiles import awatch

        while not self._stopped:
            watch_paths, alc_map, roots = self._scan()
            # Rebuilt the watch set — drop tracker state for any project that left.
            self._tracker.prune(set(roots))
            if not watch_paths:
                await asyncio.sleep(self._poll_ms / 1000)
                continue

            self._refresh = False
            try:
                async for changes in awatch(
                    *watch_paths.keys(),
                    # DefaultFilter is NOT reusable here — it ignores .git wholesale,
                    # which would blind us to every commit. Our filter keeps the
                    # precise .git refs a commit touches.
                    watch_filter=lambda _change, p: is_repo_watch_path(p),
                    yield_on_timeout=True,
                    rust_timeout=self._poll_ms,
                ):
                    if self._stopped or self._refresh:
                        break
                    for _change, raw_path in changes:
                        self._handle(Path(raw_path), alc_map, watch_paths)
                    # Every iteration — including the empty timeout ticks — is a
                    # debounce clock edge, so this is the tracker's only timer.
                    self._tracker.flush(roots)
            except (FileNotFoundError, RuntimeError):
                # A watched dir vanished (project removed) — recompute and retry.
                await asyncio.sleep(self._poll_ms / 1000)

    def _handle(
        self,
        path: Path,
        alc_map: dict[Path, str],
        root_map: dict[Path, str],
    ) -> None:
        """Classify one changed path: .alc/ message stream FIRST, else mark status.

        The ``.alc/``-membership resolution and run-log tailing are unchanged — a
        control-plane write still classifies exactly as before. Only when a path
        is NOT under any ``.alc/`` but IS under a watched root (or its external
        ``.git``) do we mark the RepoStatusTracker for a debounced status read. So
        a ``.alc/``-only event never triggers a recompute; a commit that archives
        ``.alc`` still touches ``.git/index``, which marks it via that path.
        """
        resolved = path.resolve()
        for alc_dir, project_id in alc_map.items():
            try:
                resolved.relative_to(alc_dir)
            except ValueError:
                continue
            message = classify_change(alc_dir, path)
            if message is None:
                return
            if message["type"] == "run":
                self._emit_run_lines(project_id, path)
                return
            message["project_id"] = project_id
            self._bus.publish(message)
            return

        for base, project_id in root_map.items():
            try:
                resolved.relative_to(base)
            except ValueError:
                continue
            self._tracker.mark(project_id)
            return

    def _emit_run_lines(self, project_id: str, path: Path) -> None:
        """Publish only the NEW lines of a run log as ``run_event`` messages."""
        try:
            lines = path.read_text().splitlines()
        except OSError:
            return
        start = self._offsets.get(path, 0)
        for line in lines[start:]:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._bus.publish(
                {
                    "type": "run_event",
                    "project_id": project_id,
                    "stem": path.stem,
                    "event": event,
                }
            )
        self._offsets[path] = len(lines)
