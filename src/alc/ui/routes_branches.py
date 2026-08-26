# routes_branches.py — `alc/*` branch actions: list, land, discard.
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from alc.ui import review, service
from alc.ui.deps import ProjectContext, get_project

router = APIRouter(prefix="/api/projects/{id}", tags=["branches"])


class LandBody(BaseModel):
    """Body for POST /branches/land: branches to integrate (or every unmerged
    one), plus the optional delivery override for the push/PR last mile
    (DeliverySpec, roadmap-phase-4.md T8). Omitted `mode`/`remote`/`base`
    fall back to the project manifest's own `delivery` block, then to
    `local` — same precedence as CLI `_resolve_delivery`."""

    branches: list[str] | None = None
    mode: Literal["local", "push", "pr"] | None = None
    remote: str | None = None
    base: str | None = None


class ReviewComment(BaseModel):
    """One line-anchored review note."""

    path: str
    line: int | None = None
    text: str


class ReviewBody(BaseModel):
    """Body for POST /branches/review: the notes, and the unit to run them as."""

    branch: str
    comments: list[ReviewComment]
    kind: Literal["flow", "specialist"] = "flow"
    name: str | None = None
    engine: str | None = None


class BundlesSpec(BaseModel):
    """The `--bundles --older-than N` half of a discard: delete old bundle files."""

    older_than_days: int


class DiscardBody(BaseModel):
    """Body for POST /branches/discard: branches to delete, plus optional prune steps."""

    branches: list[str] = []
    worktrees: bool = False
    bundles: BundlesSpec | None = None


@router.get("/branches")
def get_branches(ctx: ProjectContext = Depends(get_project)) -> dict:
    return service.list_branches(ctx.root)


@router.post("/branches/land")
def land(body: LandBody, ctx: ProjectContext = Depends(get_project)) -> dict:
    return service.land_branches(
        ctx.root, body.branches, mode=body.mode, remote=body.remote, base=body.base
    )


@router.get("/branches/diff")
def get_branch_diff(branch: str, ctx: ProjectContext = Depends(get_project)) -> dict:
    # `branch` is a QUERY param: an alc/* name carries a `/`, which a path param
    # would split (same reason /variants/diff takes `?branch=`).
    return service.alc_branch_diff(ctx.root, branch)


@router.post("/branches/review")
def submit_review(body: ReviewBody, ctx: ProjectContext = Depends(get_project)) -> dict:
    return review.submit_review(
        ctx.root,
        body.branch,
        [c.model_dump() for c in body.comments],
        kind=body.kind,
        name=body.name,
        engine=body.engine,
    )


@router.post("/branches/discard")
def discard(body: DiscardBody, ctx: ProjectContext = Depends(get_project)) -> dict:
    return service.discard_branches(
        ctx.root,
        body.branches,
        worktrees=body.worktrees,
        older_than_days=body.bundles.older_than_days if body.bundles else None,
    )
