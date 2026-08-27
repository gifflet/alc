# routes_browse.py — Read-only filesystem browsing, so a project can be picked.
from __future__ import annotations

import subprocess
from dataclasses import asdict

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from alc.ui import browse, clone
from alc.ui.errors import ApiError

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


class NewProjectRequest(BaseModel):
    """Body for creating a project from nothing."""

    parent: str
    name: str
    #: Run `git init` first. On by default because isolation, landing and the
    #: commit step all need a repository — a project without one silently loses
    #: half of what ALC does.
    git: bool = True


@router.post("/new-project", status_code=202)
def new_project(body: NewProjectRequest, request: Request) -> dict:
    """Create a directory and scaffold an Operator Layer in it.

    Returns the exec to follow, like a clone: `alc init` detects the stack and
    can take a moment, and the UI already knows how to watch an exec.
    """
    destination = clone.resolve_new_project(body.parent, body.name)
    destination.mkdir(parents=True, exist_ok=True)

    # `git init` finishes in milliseconds, so it runs here rather than being
    # chained into the streamed command. Chaining would have meant a shell
    # string, and this codebase builds argv lists precisely to avoid one.
    if body.git:
        try:
            subprocess.run(
                ["git", "init", "-q"], cwd=destination, capture_output=True, check=True
            )
        except FileNotFoundError as exc:
            raise ApiError("git is not on PATH on the server", status=500) from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or b"").decode(errors="replace").strip()
            raise ApiError(f"git init failed: {detail}", status=500) from exc

    # `alc init` acts on the current directory, so the work happens by running
    # it *in* the new one rather than by passing a path it does not accept.
    runs = request.app.state.run_manager
    ex = runs.start(
        project_id=None,
        cwd=str(destination),
        command=f"alc init in {destination.name}",
        argv=["alc", "init"],
    )
    return {"exec_id": ex.id, "destination": str(destination)}


class AdoptRequest(BaseModel):
    """Body for setting ALC up inside a directory that already holds code."""

    path: str


@router.post("/adopt", status_code=202)
def adopt_directory(body: AdoptRequest, request: Request) -> dict:
    """Scaffold an Operator Layer inside an existing project.

    The registry refuses a directory with no .alc/manifest.yaml — correctly, since
    it is not an ALC project yet. But that left the commonest case with no way
    forward from the UI: a repository full of real code, which is exactly what
    someone wants to point ALC at first. This runs `alc init` there, after which
    registering succeeds.
    """
    directory = browse.resolve(body.path)
    if (directory / ".alc" / "manifest.yaml").is_file():
        raise ApiError(f"'{directory}' is already an ALC project", status=400)

    runs = request.app.state.run_manager
    ex = runs.start(
        project_id=None,
        cwd=str(directory),
        command=f"alc init in {directory.name}",
        argv=["alc", "init"],
    )
    return {"exec_id": ex.id, "destination": str(directory)}
