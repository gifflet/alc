# routes_browse.py — Read-only filesystem browsing, so a project can be picked.
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Query

from alc.ui import browse

router = APIRouter(prefix="/api/fs", tags=["fs"])


@router.get("/browse")
def browse_directory(
    path: str | None = Query(default=None, description="Directory to list; defaults to $HOME"),
    show_hidden: bool = Query(default=False, description="Include dot-directories"),
) -> dict:
    """List the directories inside `path`, marking which are ALC projects or git repos.

    Directories only — no file names, and nothing is ever read from a file.
    """
    return asdict(browse.list_directory(path, show_hidden=show_hidden))
