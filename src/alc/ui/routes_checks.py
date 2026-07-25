# routes_checks.py — Checks: per-check history (pass-rate/duration/flake), the
# proposed check-set audit (`alc checks history` / `alc checks audit`), and the
# harvest-only `alc onboard` proposal + apply.
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from alc.ui import service
from alc.ui.deps import ProjectContext, get_project

router = APIRouter(prefix="/api/projects/{id}", tags=["checks"])

# The product stages onboarding accepts — the SAME choices `alc onboard --stage`
# restricts to (cli.py's argparse). Restricting here rejects anything else with a
# 422 up front, so the service never has to second-guess the value.
OnboardStage = Literal["pre-pmf", "growth", "strong-pmf"]


class OnboardApplyBody(BaseModel):
    """Body for POST /checks/onboard/apply — only the operator's stage answer.

    The server rebuilds the whole proposal itself; the client never sends check
    data, so `stage` (or its absence) is the one thing this body carries.
    """

    stage: OnboardStage | None = None


@router.get("/checks/history")
def get_checks_history(ctx: ProjectContext = Depends(get_project)) -> list[dict]:
    return service.checks_history(ctx.root)


@router.get("/checks/audit")
def get_checks_audit(ctx: ProjectContext = Depends(get_project)) -> dict:
    return service.checks_audit(ctx.root)


@router.get("/checks/onboard")
def get_onboard_proposal(
    stage: OnboardStage | None = None, ctx: ProjectContext = Depends(get_project)
) -> dict:
    return service.onboard_proposal(ctx.root, stage)


@router.post("/checks/onboard/apply")
def apply_onboard(
    body: OnboardApplyBody, ctx: ProjectContext = Depends(get_project)
) -> dict:
    return service.onboard_apply(ctx.root, body.stage)
