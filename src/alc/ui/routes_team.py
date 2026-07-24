# routes_team.py — Team roster (hired Archetype Packs) and hire.
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from alc.ui import service
from alc.ui.deps import ProjectContext, get_project
from alc.ui.watch import classify_change

router = APIRouter(prefix="/api/projects/{id}", tags=["team"])


class HireBody(BaseModel):
    """Body for POST /team/hire: the archetype to hire, optionally forcing overwrite."""

    archetype: str
    force: bool = False


class RetireBody(BaseModel):
    """Body for POST /team/retire: the archetype (member) to retire.

    Named `archetype`, not `member`, matching `HireBody` — the two verbs act
    on the same roster entry, so their bodies stay consistent.
    """

    archetype: str


@router.get("/team")
def get_team(ctx: ProjectContext = Depends(get_project)) -> dict:
    return service.team_roster(ctx.root)


@router.post("/team/hire", status_code=201)
def hire(
    body: HireBody, request: Request, ctx: ProjectContext = Depends(get_project)
) -> dict:
    result = service.team_hire(ctx.root, body.archetype, force=body.force)
    _notify_files_changed(request, ctx, result["written"])
    return result


@router.post("/team/retire")
def retire(
    body: RetireBody, request: Request, ctx: ProjectContext = Depends(get_project)
) -> dict:
    result = service.team_retire(ctx.root, body.archetype)
    _notify_files_changed(request, ctx, result["moved"])
    return result


def _notify_files_changed(request: Request, ctx: ProjectContext, paths: list[str]) -> None:
    """Publish the collection-changed WS event(s) a hire's writes or a retire's
    moves produce.

    Reuses `watch.classify_change` — the SAME classifier the file watcher runs
    on disk changes — so a hire/retire announces exactly the events the project
    tree and the roster already know how to react to; no new WS message type.
    One message per distinct (type, resource/name) pair, deduplicated, since a
    pack commonly touches several files under the same collection.
    """
    bus = request.app.state.bus
    seen: set[tuple[tuple[str, object], ...]] = set()
    for rel_path in paths:
        message = classify_change(ctx.operator_layer, ctx.root / rel_path)
        if message is None:
            continue
        key = tuple(sorted(message.items()))
        if key in seen:
            continue
        seen.add(key)
        message["project_id"] = ctx.project.id
        bus.publish(message)
