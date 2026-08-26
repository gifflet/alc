# routes_inbox.py — The operator's decision queue.
from __future__ import annotations

from fastapi import APIRouter, Depends

from alc.ui import inbox
from alc.ui.deps import ProjectContext, get_project

router = APIRouter(prefix="/api/projects/{id}", tags=["inbox"])


@router.get("/inbox")
def get_inbox(ctx: ProjectContext = Depends(get_project)) -> dict:
    return inbox.build_inbox(ctx.root)
