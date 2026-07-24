# routes_signals.py — Signal intake: ingest + list the pending queue.
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Body, Depends, Request

from alc.ui import service
from alc.ui.deps import ProjectContext, get_project
from alc.ui.watch import classify_change

router = APIRouter(prefix="/api/projects/{id}", tags=["signals"])


@router.get("/signals")
def get_signals(ctx: ProjectContext = Depends(get_project)) -> list[dict]:
    return service.list_signals(ctx.root)


@router.post("/signals", status_code=201)
def post_signal(
    request: Request, data: dict = Body(...), ctx: ProjectContext = Depends(get_project)
) -> dict:
    result = service.ingest_signal(ctx.root, data)
    _notify_signal_changed(request, ctx, Path(result["path"]))
    return result


def _notify_signal_changed(request: Request, ctx: ProjectContext, path: Path) -> None:
    """Publish the signals-changed WS event a successful ingest produces.

    Reuses `watch.classify_change` — the SAME classifier the file watcher runs
    on disk changes (as `routes_team._notify_files_changed` does for a hire)
    — so an ingest announces exactly the event a signals panel already knows
    how to react to; no new WS message type.
    """
    message = classify_change(ctx.operator_layer, path)
    if message is None:
        return
    message["project_id"] = ctx.project.id
    request.app.state.bus.publish(message)
