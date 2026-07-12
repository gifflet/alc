# routes_queue.py — Per-project queue, runs, lint, engines and scorecard.
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Response
from pydantic import BaseModel

from alc.ui import service
from alc.ui.deps import ProjectContext, get_project

router = APIRouter(prefix="/api/projects/{id}", tags=["queue"])


class RetryBody(BaseModel):
    """Body for POST /queue/retry: a single stem or all outstanding failures."""

    stem: str | None = None
    all: bool = False


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------


@router.get("/queue")
def get_queue(ctx: ProjectContext = Depends(get_project)) -> dict:
    return service.read_queue(ctx.root)


@router.post("/queue", status_code=201)
def enqueue(task: dict = Body(...), ctx: ProjectContext = Depends(get_project)) -> dict:
    return {"stem": service.enqueue(ctx.root, task)}


@router.delete("/queue/{stem}", status_code=204)
def delete_pending(stem: str, ctx: ProjectContext = Depends(get_project)) -> Response:
    service.delete_pending(ctx.root, stem)
    return Response(status_code=204)


@router.post("/queue/retry")
def retry(body: RetryBody, ctx: ProjectContext = Depends(get_project)) -> dict:
    return service.retry_queue(ctx.root, stem=body.stem, all_=body.all)


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


@router.get("/runs")
def list_runs(
    ctx: ProjectContext = Depends(get_project), limit: int = 50, offset: int = 0
) -> dict:
    return service.list_runs(ctx.root, limit=limit, offset=offset)


@router.get("/runs/{stem}")
def get_run(
    stem: str, ctx: ProjectContext = Depends(get_project), offset: int = 0
) -> dict:
    return service.read_run(ctx.root, stem, offset=offset)


# ---------------------------------------------------------------------------
# Lint / engines / scorecard
# ---------------------------------------------------------------------------


@router.get("/lint")
def get_lint(ctx: ProjectContext = Depends(get_project)) -> dict:
    return service.lint_project(ctx.root)


@router.get("/engines")
def get_engines(ctx: ProjectContext = Depends(get_project)) -> list[dict]:
    return service.engines_info(ctx.root)


@router.get("/scorecard")
def get_scorecard(ctx: ProjectContext = Depends(get_project)) -> dict:
    return service.scorecard(ctx.root)
