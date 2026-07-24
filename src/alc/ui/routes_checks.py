# routes_checks.py — Checks: per-check history (pass-rate/duration/flake) and
# the proposed check-set audit (`alc checks history` / `alc checks audit`).
from __future__ import annotations

from fastapi import APIRouter, Depends

from alc.ui import service
from alc.ui.deps import ProjectContext, get_project

router = APIRouter(prefix="/api/projects/{id}", tags=["checks"])


@router.get("/checks/history")
def get_checks_history(ctx: ProjectContext = Depends(get_project)) -> list[dict]:
    return service.checks_history(ctx.root)


@router.get("/checks/audit")
def get_checks_audit(ctx: ProjectContext = Depends(get_project)) -> dict:
    return service.checks_audit(ctx.root)
