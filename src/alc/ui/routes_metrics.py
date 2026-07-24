# routes_metrics.py — Per-project measurement: metric series, artifact
# evidence (list + bytes) and the audit window.
from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from alc.ui import service
from alc.ui.deps import ProjectContext, get_project

router = APIRouter(prefix="/api/projects/{id}", tags=["metrics"])


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@router.get("/metrics")
def get_metrics(
    check: str | None = None, ctx: ProjectContext = Depends(get_project)
) -> dict:
    return service.metric_series(ctx.root, check=check)


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------


@router.get("/runs/{stem}/artifacts")
def get_run_artifacts(stem: str, ctx: ProjectContext = Depends(get_project)) -> dict:
    return service.run_artifacts(ctx.root, stem)


@router.get("/artifacts")
def get_latest_artifacts(ctx: ProjectContext = Depends(get_project)) -> dict:
    return service.latest_artifacts(ctx.root)


@router.get("/artifacts/file")
def get_artifact_file(
    path: str, ctx: ProjectContext = Depends(get_project)
) -> FileResponse:
    file_path = service.artifact_file_path(ctx.root, path)
    media_type, _ = mimetypes.guess_type(str(file_path))
    return FileResponse(file_path, media_type=media_type)


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


@router.get("/audit")
def get_audit(since: str, ctx: ProjectContext = Depends(get_project)) -> dict:
    return service.audit(ctx.root, since)
