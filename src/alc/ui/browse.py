"""browse.py — Read-only directory listing, so a project can be picked instead of typed.

Registering a project used to mean pasting an absolute path, which means knowing
it by heart or leaving the browser to go find it. This lets the UI walk the
filesystem of the machine running the server.

That is a real widening of what the API exposes, so the rules are narrow on
purpose:

* Directories only. File names are never returned, and no file is ever read.
* Symlinks are resolved before use, so a link cannot be followed to a place the
  caller could not have named directly — and the resolved path is what comes
  back, so the UI never shows one location while meaning another.
* Dot-directories stay hidden unless asked for. They are noise when picking a
  project, and quieter is the better default for something that lists a home
  directory.
* Unreadable entries are skipped rather than raising. One directory with tight
  permissions should not make its parent unlistable.

The endpoint sits behind the same token gate as the rest of the API. With no
token configured the server is what it has always been: unauthenticated on
localhost.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from alc.ui.errors import ApiError


@dataclass(frozen=True)
class Entry:
    """One directory the caller may descend into or pick."""

    name: str
    path: str
    is_alc_project: bool
    is_git_repo: bool


@dataclass(frozen=True)
class Listing:
    """A resolved directory and the directories directly inside it."""

    path: str
    parent: str | None
    is_alc_project: bool
    is_git_repo: bool
    entries: list[Entry]


def default_root() -> Path:
    """Where the browser opens when the caller names nothing."""
    return Path.home()


def _classify(directory: Path) -> tuple[bool, bool]:
    """Whether the directory is an ALC project and/or a git repository."""
    try:
        return (directory / ".alc").is_dir(), (directory / ".git").exists()
    except OSError:
        # A directory we cannot stat is simply neither, rather than a failure.
        return False, False


def resolve(raw: str | None) -> Path:
    """Turn a requested path into an absolute, symlink-free directory.

    Raises ApiError when the path does not exist or is not a directory, so the
    UI can say which of the two is wrong instead of showing an empty list.
    """
    candidate = Path(raw).expanduser() if raw else default_root()
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise ApiError(f"cannot resolve '{candidate}': {exc}", status=400) from exc
    if not resolved.exists():
        raise ApiError(f"'{resolved}' does not exist", status=404)
    if not resolved.is_dir():
        raise ApiError(f"'{resolved}' is not a directory", status=400)
    return resolved


def list_directory(raw: str | None, *, show_hidden: bool = False) -> Listing:
    """List the directories inside `raw` (or the home directory)."""
    directory = resolve(raw)

    try:
        children = sorted(
            (e for e in os.scandir(directory)),
            key=lambda e: e.name.lower(),
        )
    except PermissionError as exc:
        raise ApiError(f"permission denied reading '{directory}'", status=403) from exc
    except OSError as exc:
        raise ApiError(f"cannot read '{directory}': {exc}", status=400) from exc

    entries: list[Entry] = []
    for child in children:
        if not show_hidden and child.name.startswith("."):
            continue
        try:
            # follow_symlinks is the default; a link to a directory is offered as
            # the directory it points at, which is what the operator means.
            if not child.is_dir():
                continue
        except OSError:
            continue
        child_path = Path(child.path)
        is_alc, is_git = _classify(child_path)
        entries.append(
            Entry(
                name=child.name,
                path=str(child_path),
                is_alc_project=is_alc,
                is_git_repo=is_git,
            )
        )

    is_alc, is_git = _classify(directory)
    parent = directory.parent
    return Listing(
        path=str(directory),
        # At the filesystem root, parent == directory; reporting that as a step
        # up would render a control that goes nowhere.
        parent=str(parent) if parent != directory else None,
        is_alc_project=is_alc,
        is_git_repo=is_git,
        entries=entries,
    )
