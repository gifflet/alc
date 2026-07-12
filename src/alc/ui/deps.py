# deps.py — FastAPI dependency resolving a project id to its on-disk context.
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import Request

from alc.ui.errors import ApiError
from alc.ui.registry import RegisteredProject


@dataclass
class ProjectContext:
    """A resolved project: its registry entry plus its filesystem paths."""

    project: RegisteredProject
    root: Path
    operator_layer: Path


def get_project(id: str, request: Request) -> ProjectContext:
    """Resolve the ``{id}`` path parameter to a ProjectContext.

    Raises ApiError(404) for an unknown id and ApiError(410) when the project no
    longer holds a ``.alc/manifest.yaml`` (deregistered on disk).
    """
    registry = request.app.state.registry
    project = registry.get(id)
    if project is None:
        raise ApiError(f"unknown project '{id}'", status=404)
    root = Path(project.path)
    if not (root / ".alc" / "manifest.yaml").is_file():
        raise ApiError(f"project '{id}' no longer has a .alc/manifest.yaml", status=410)
    return ProjectContext(project=project, root=root, operator_layer=root / ".alc")
