# routes_browse.py — Read-only filesystem browsing, so a project can be picked.
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from alc.ui import browse, clone

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


class CloneRequest(BaseModel):
    """Body for cloning a repository into a directory on the host."""

    url: str
    parent: str
    name: str | None = None


@router.post("/clone", status_code=202)
def clone_repository(body: CloneRequest, request: Request) -> dict:
    """Start `git clone` and stream its progress over the WebSocket.

    Returns immediately with the exec id: a clone can take minutes, and a
    request that blocks for minutes is one a proxy eventually kills. The UI
    follows `exec_output` / `exec_finished` the same way it follows a run.
    """
    url = clone.validate_url(body.url)
    destination = clone.resolve_destination(body.parent, url, body.name)

    runs = request.app.state.run_manager
    ex = runs.start(
        # None, not "": a clone belongs to no project yet, and the bus treats
        # a None project_id as global — which is the only scope that reaches a
        # client who has not subscribed to anything.
        project_id=None,
        cwd=str(destination.parent),
        command=f"git clone {url}",
        argv=clone.build_argv(url, destination),
    )
    return {"exec_id": ex.id, "destination": str(destination)}
