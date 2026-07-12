# routes_run_configs.py — The command schema + per-project run configurations.
#
# GET /api/commands exposes the command whitelist so the frontend can render a
# config form generically. The per-project routes are a thin CRUD over
# run_configs.py; running a config reuses POST /exec, so there is no run route.
from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from alc.ui import run_configs
from alc.ui.command import command_schema
from alc.ui.deps import ProjectContext, get_project
from alc.ui.run_configs import RunConfig

# The command schema is app-level (it does not need a project); the CRUD lives
# under the project prefix like the other per-project routers.
router = APIRouter(prefix="/api/commands", tags=["run-configs"])
project_router = APIRouter(prefix="/api/projects/{id}", tags=["run-configs"])


@router.get("")
def get_commands() -> dict:
    """Return the whitelist of runnable commands and their accepted arguments."""
    return command_schema()


@project_router.get("/run-configs")
def list_run_configs(ctx: ProjectContext = Depends(get_project)) -> dict:
    return {"configs": run_configs.load_run_configs(ctx.root)}


@project_router.post("/run-configs", status_code=201)
def create_run_config(
    config: RunConfig, ctx: ProjectContext = Depends(get_project)
) -> RunConfig:
    return run_configs.add_run_config(ctx.root, config)


@project_router.put("/run-configs/{name}")
def update_run_config(
    name: str, config: RunConfig, ctx: ProjectContext = Depends(get_project)
) -> RunConfig:
    return run_configs.update_run_config(ctx.root, name, config)


@project_router.delete("/run-configs/{name}", status_code=204)
def delete_run_config(name: str, ctx: ProjectContext = Depends(get_project)) -> Response:
    run_configs.delete_run_config(ctx.root, name)
    return Response(status_code=204)
