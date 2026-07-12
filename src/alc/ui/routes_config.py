# routes_config.py — Per-project config: manifest, collections and prompts.
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from alc.intake import load_manifest
from alc.ui import collections, service
from alc.ui.deps import ProjectContext, get_project

router = APIRouter(prefix="/api/projects/{id}", tags=["config"])


class RawBody(BaseModel):
    """Body carrying a raw file payload for PUT."""

    raw: str


class CreateBody(BaseModel):
    """Body for creating a collection unit (name + optional raw)."""

    name: str
    raw: str = ""


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


@router.get("/manifest")
def get_manifest(ctx: ProjectContext = Depends(get_project)) -> dict:
    return service.read_manifest(ctx.root)


@router.put("/manifest")
def put_manifest(body: RawBody, ctx: ProjectContext = Depends(get_project)) -> dict:
    return service.write_manifest(ctx.root, body.raw)


# ---------------------------------------------------------------------------
# Prompts (reserved / free / ejected)
# ---------------------------------------------------------------------------


@router.get("/prompts")
def list_prompts(ctx: ProjectContext = Depends(get_project)) -> list[dict]:
    return service.list_prompts_view(ctx.root)


@router.get("/prompts/{name}")
def get_prompt(name: str, ctx: ProjectContext = Depends(get_project)) -> dict:
    return service.read_prompt(ctx.root, name)


@router.put("/prompts/{name}")
def put_prompt(name: str, body: RawBody, ctx: ProjectContext = Depends(get_project)) -> dict:
    return service.write_prompt(ctx.root, name, body.raw, create=False)


@router.post("/prompts", status_code=201)
def create_prompt(body: CreateBody, ctx: ProjectContext = Depends(get_project)) -> dict:
    return service.write_prompt(ctx.root, body.name, body.raw, create=True)


@router.delete("/prompts/{name}", status_code=204)
def delete_prompt(name: str, ctx: ProjectContext = Depends(get_project)) -> Response:
    service.delete_prompt(ctx.root, name)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Loops: state + ledger (must precede the generic /{collection}/{name} routes)
# ---------------------------------------------------------------------------


@router.get("/loops/{name}/state")
def get_loop_state(name: str, ctx: ProjectContext = Depends(get_project)) -> dict:
    return service.read_loop_state(ctx.root, name)


@router.get("/loops/{name}/ledger")
def get_loop_ledger(name: str, ctx: ProjectContext = Depends(get_project)) -> dict:
    return service.read_loop_ledger(ctx.root, name)


# ---------------------------------------------------------------------------
# Generic collections: blueprints / flows / specialists / loops / primers
# ---------------------------------------------------------------------------


@router.get("/{collection}")
def list_collection(collection: str, ctx: ProjectContext = Depends(get_project)) -> list[dict]:
    spec = collections.get_spec(collection)
    manifest = load_manifest(ctx.operator_layer)
    return collections.list_items(spec, ctx.root, manifest)


@router.get("/{collection}/{name}")
def get_collection_item(
    collection: str, name: str, ctx: ProjectContext = Depends(get_project)
) -> dict:
    spec = collections.get_spec(collection)
    manifest = load_manifest(ctx.operator_layer)
    return collections.read_item(spec, ctx.root, manifest, name)


@router.put("/{collection}/{name}")
def put_collection_item(
    collection: str, name: str, body: RawBody, ctx: ProjectContext = Depends(get_project)
) -> dict:
    spec = collections.get_spec(collection)
    manifest = load_manifest(ctx.operator_layer)
    return collections.write_item(spec, ctx.root, manifest, name, body.raw, create=False)


@router.post("/{collection}", status_code=201)
def create_collection_item(
    collection: str, body: CreateBody, ctx: ProjectContext = Depends(get_project)
) -> dict:
    spec = collections.get_spec(collection)
    manifest = load_manifest(ctx.operator_layer)
    return collections.write_item(spec, ctx.root, manifest, body.name, body.raw, create=True)


@router.delete("/{collection}/{name}", status_code=204)
def delete_collection_item(
    collection: str, name: str, ctx: ProjectContext = Depends(get_project)
) -> Response:
    spec = collections.get_spec(collection)
    manifest = load_manifest(ctx.operator_layer)
    collections.delete_item(spec, ctx.root, manifest, name)
    return Response(status_code=204)
