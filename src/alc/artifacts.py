# artifacts.py — `alc artifacts`: read back the e2e evidence a `needs_service`
# run's `capture:` command produced.
#
# RunReport.artifacts is never persisted to a ledger of its own — it rides the
# `mandate_finished` event already written to the run log (`alc.events`), the
# same place `alc.runs._net_lines` reads `diffstat` back out of. Read-only,
# same convention as `alc checks history` / `alc metrics`: this module never
# writes, closing "verified end-to-end" with proof of execution rather than
# just an exit code.
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# Extension -> display label for `alc artifacts`' "type" column. Sugar only —
# not a schema, not interpreted anywhere else. Anything unrecognised is "file".
_TYPE_BY_SUFFIX = {
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".webp": "image",
    ".log": "log",
    ".txt": "log",
    ".json": "data",
    ".html": "data",
}


def artifact_type(path: str) -> str:
    """Classify *path* by its extension for display; unknown extensions -> "file"."""
    return _TYPE_BY_SUFFIX.get(Path(path).suffix.lower(), "file")


@dataclass
class RunArtifacts:
    """One run's captured evidence: its run-log stem and every artifact path."""

    stem: str
    artifacts: list[str]


def _iter_mandate_finished(path: Path):
    """Yield every well-formed `mandate_finished` event in *path*, in file order.

    Best-effort, mirroring `checks._iter_check_finished`: an unreadable file or
    a malformed JSON line is skipped rather than aborting the read.
    """
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("event") == "mandate_finished":
            yield event


def _read_artifacts(path: Path) -> list[str]:
    """Return every artifact path recorded across *path*'s `mandate_finished` events.

    A flow/task run log holds one `mandate_finished` per stage (same reasoning
    as `runs._net_lines`) — collects across all of them, de-duplicated, in the
    order first seen.
    """
    seen: list[str] = []
    for event in _iter_mandate_finished(path):
        for artifact in event.get("artifacts") or []:
            if isinstance(artifact, str) and artifact not in seen:
                seen.append(artifact)
    return seen


def run_artifacts(runs_dir: Path, stem: str) -> RunArtifacts:
    """Return the artifacts recorded for run *stem*.

    Raises FileNotFoundError when no such run log exists (mirrors `alc.runs.read_run`).
    """
    path = runs_dir / f"{stem}.jsonl"
    if not path.is_file():
        raise FileNotFoundError(f"no run '{stem}'")
    return RunArtifacts(stem=stem, artifacts=_read_artifacts(path))


def latest_run_with_artifacts(runs_dir: Path) -> RunArtifacts | None:
    """Return the most recently modified run log that has at least one artifact.

    None when *runs_dir* is absent or no run log has recorded an artifact yet.
    """
    if not runs_dir.is_dir():
        return None
    for log_file in sorted(
        runs_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
    ):
        found = _read_artifacts(log_file)
        if found:
            return RunArtifacts(stem=log_file.stem, artifacts=found)
    return None
