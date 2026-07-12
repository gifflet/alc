# watch.py — Watch each registered project's .alc/ and publish changes to the bus.
#
# classify_change() is a PURE function (path -> message) so it is unit-tested
# without watchfiles. Watcher wraps watchfiles.awatch over the union of the
# registered projects' .alc/ directories, refreshing when projects are added or
# removed at runtime. For run logs it keeps a per-file line offset and publishes
# only the NEW lines as ``run_event`` messages.
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from alc.ui.bus import EventBus
from alc.ui.registry import ProjectRegistry


def _strip_loop_suffix(name: str) -> str:
    """Return the loop name from a loops/ filename (state/ledger/def)."""
    for suffix in (".state.json", ".ledger.jsonl", ".yaml"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


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

    if rel.name == "manifest.yaml" and len(parts) == 1:
        return {"type": "config_changed", "resource": "manifest"}

    if top in ("blueprints", "flows", "specialists", "primers", "prompts"):
        return {"type": "config_changed", "resource": top}

    return None


class Watcher:
    """Async file watcher fanning ``.alc/`` changes out to the EventBus."""

    def __init__(self, registry: ProjectRegistry, bus: EventBus, poll_ms: int = 400) -> None:
        self._registry = registry
        self._bus = bus
        self._poll_ms = poll_ms
        self._task: asyncio.Task | None = None
        self._stopped = False
        self._refresh = False
        self._offsets: dict[Path, int] = {}

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

    def _watched(self) -> dict[Path, str]:
        """Return {alc_dir: project_id} for every currently registered project."""
        watched: dict[Path, str] = {}
        for project in self._registry.list():
            alc_dir = Path(project.path) / ".alc"
            if alc_dir.is_dir():
                watched[alc_dir.resolve()] = project.id
        return watched

    async def _run(self) -> None:
        """Watch the current project set, restarting when the registry changes."""
        from watchfiles import awatch

        while not self._stopped:
            watched = self._watched()
            if not watched:
                await asyncio.sleep(self._poll_ms / 1000)
                continue

            self._refresh = False
            try:
                async for changes in awatch(
                    *watched.keys(),
                    yield_on_timeout=True,
                    rust_timeout=self._poll_ms,
                ):
                    if self._stopped or self._refresh:
                        break
                    for _change, raw_path in changes:
                        self._handle(Path(raw_path), watched)
            except (FileNotFoundError, RuntimeError):
                # A watched dir vanished (project removed) — recompute and retry.
                await asyncio.sleep(self._poll_ms / 1000)

    def _handle(self, path: Path, watched: dict[Path, str]) -> None:
        """Classify one changed path against its owning project and publish."""
        for alc_dir, project_id in watched.items():
            try:
                path.resolve().relative_to(alc_dir)
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
