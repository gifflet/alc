# routes_variants.py — Explore/compare/adopt: variants archived under `manifest.variants_dir`.
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from alc.ui import service
from alc.ui.deps import ProjectContext, get_project

router = APIRouter(prefix="/api/projects/{id}", tags=["variants"])


class AdoptBody(BaseModel):
    """Body for POST /variants/adopt: the winning variant branch to integrate."""

    branch: str


@router.get("/variants")
def get_variants(ctx: ProjectContext = Depends(get_project)) -> list[dict]:
    return service.list_variants(ctx.root)


@router.get("/variants/diff")
def get_variant_diff(branch: str, ctx: ProjectContext = Depends(get_project)) -> dict:
    # `branch` is a QUERY param, not a path segment: an alc/* branch name carries
    # a `/`, which a path param would split (same reason /artifacts/file takes
    # `?path=`). Declared before nothing else can shadow it — `/variants/diff` is
    # a literal path, so it never collides with the bare `/variants`.
    return service.variant_diff(ctx.root, branch)


@router.post("/variants/adopt")
def adopt(body: AdoptBody, ctx: ProjectContext = Depends(get_project)) -> dict:
    return service.adopt_variant(ctx.root, body.branch)
