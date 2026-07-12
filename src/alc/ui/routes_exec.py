# routes_exec.py — Dispatch `alc` execs and inspect/cancel them.
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from alc.ui.command import build_argv
from alc.ui.deps import ProjectContext, get_project
from alc.ui.errors import ApiError

# Per-project dispatch lives under the project prefix; exec inspection is global.
project_router = APIRouter(prefix="/api/projects/{id}", tags=["exec"])
router = APIRouter(prefix="/api/execs", tags=["exec"])


class ExecBody(BaseModel):
    """Body for POST /exec: a whitelisted command and its arguments."""

    command: str
    args: dict = {}


@project_router.post("/exec", status_code=201)
def start_exec(body: ExecBody, request: Request, ctx: ProjectContext = Depends(get_project)) -> dict:
    """Spawn an `alc` subprocess for this project and return its exec id."""
    argv = build_argv(body.command, body.args)
    run_manager = request.app.state.run_manager
    ex = run_manager.start(ctx.project.id, str(ctx.root), body.command, argv)
    return {"exec_id": ex.id}


@router.get("")
def list_execs(request: Request) -> list[dict]:
    """List every tracked exec (across all projects)."""
    return [ex.view() for ex in request.app.state.run_manager.list()]


@router.get("/{exec_id}")
def get_exec(exec_id: str, request: Request) -> dict:
    """Return one exec's status and buffered output tail."""
    ex = request.app.state.run_manager.get(exec_id)
    if ex is None:
        raise ApiError(f"unknown exec '{exec_id}'", status=404)
    return ex.view()


@router.post("/{exec_id}/cancel")
def cancel_exec(exec_id: str, request: Request) -> dict:
    """Terminate a running exec (SIGKILL after a grace period)."""
    run_manager = request.app.state.run_manager
    if run_manager.get(exec_id) is None:
        raise ApiError(f"unknown exec '{exec_id}'", status=404)
    cancelled = run_manager.cancel(exec_id)
    return {"cancelled": cancelled}
