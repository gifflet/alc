# routes_fleet.py — The live fleet: runs executing right now.
from __future__ import annotations

from fastapi import APIRouter, Depends

from alc.ui import service
from alc.ui.deps import ProjectContext, get_project

router = APIRouter(prefix="/api/projects/{id}", tags=["fleet"])


@router.get("/fleet")
def get_fleet(ctx: ProjectContext = Depends(get_project)) -> dict:
    return service.fleet(ctx.root)
