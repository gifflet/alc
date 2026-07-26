# routes_projects.py — Registry endpoints: list / register / deregister projects.
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from alc.ui import service
from alc.ui.deps import ProjectContext, get_project
from alc.ui.errors import ApiError

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    """Body for registering a project."""

    path: str
    name: str | None = None


def _notify_project_list_changed(request: Request) -> None:
    """Publish a global project_list_changed and refresh the file watcher."""
    request.app.state.bus.publish({"type": "project_list_changed", "project_id": None})
    request.app.state.watcher.refresh()


@router.get("")
def list_projects(request: Request) -> list[dict]:
    """List every registered project with a lightweight summary."""
    registry = request.app.state.registry
    return [
        service.project_summary(p.id, p.name, p.path) for p in registry.list()
    ]


@router.post("", status_code=201)
def create_project(body: ProjectCreate, request: Request) -> dict:
    """Register a project by path; validates it is a real ALC project."""
    registry = request.app.state.registry
    project = registry.add(body.path, body.name)
    _notify_project_list_changed(request)
    return service.project_summary(project.id, project.name, project.path)


@router.delete("/{id}", status_code=204)
def delete_project(id: str, request: Request) -> Response:
    """Deregister a project (never touches its files on disk)."""
    registry = request.app.state.registry
    if not registry.remove(id):
        raise ApiError(f"unknown project '{id}'", status=404)
    _notify_project_list_changed(request)
    return Response(status_code=204)


# This `{id}`-scoped read lives here (registered BEFORE routes_config, so its
# explicit `/{id}/worktree` path is never shadowed by the collection catch-all
# `/{id}/{collection}`) — its "projects" tag also names it honestly as a
# project-level status, not a checks concern.
@router.get("/{id}/worktree")
def get_worktree(ctx: ProjectContext = Depends(get_project)) -> dict:
    """Whether the working tree is dirty outside ``.alc/`` (blocks an autonomous run)."""
    return service.worktree_status(ctx.root)
