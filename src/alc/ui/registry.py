# registry.py — Project registry for the UI backend (~/.alc/ui/projects.json).
#
# A single JSON file tracks the projects the UI manages, by absolute path. Each
# project gets a STABLE id = slug(dir name) + short hash of the resolved path, so
# the same directory always maps to the same id across restarts.
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel

from alc.textutil import slugify
from alc.ui.errors import ApiError


class RegisteredProject(BaseModel):
    """One project tracked by the UI registry."""

    id: str
    name: str
    path: str


def default_registry_path() -> Path:
    """Return the default registry location: ``~/.alc/ui/projects.json``."""
    return Path.home() / ".alc" / "ui" / "projects.json"


def project_id(path: Path) -> str:
    """Return a stable id for *path*: slug of the dir name + short path hash."""
    resolved = path.resolve()
    digest = hashlib.sha256(str(resolved).encode()).hexdigest()[:8]
    slug = slugify(resolved.name) or "project"
    return f"{slug}-{digest}"


class ProjectRegistry:
    """CRUD over the projects.json file (a list of {id, name, path})."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _read(self) -> list[RegisteredProject]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return []
        return [RegisteredProject.model_validate(item) for item in raw]

    def _write(self, projects: list[RegisteredProject]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps([p.model_dump() for p in projects], indent=2)
        )

    def list(self) -> list[RegisteredProject]:
        """Return every registered project."""
        return self._read()

    def get(self, id: str) -> RegisteredProject | None:
        """Return the project with this id, or None."""
        for project in self._read():
            if project.id == id:
                return project
        return None

    def add(self, path: str | Path, name: str | None = None) -> RegisteredProject:
        """Register a project by path; validates it is a real ALC project.

        Idempotent: registering an already-known path returns the existing entry.

        Raises:
            ApiError(400): if the path is missing or has no .alc/manifest.yaml.
        """
        root = Path(path).expanduser()
        if not root.is_dir():
            raise ApiError(f"path does not exist or is not a directory: {path}", status=400)
        if not (root / ".alc" / "manifest.yaml").is_file():
            raise ApiError(
                f"no .alc/manifest.yaml under {root} — not an ALC project", status=400
            )
        root = root.resolve()
        pid = project_id(root)

        projects = self._read()
        for project in projects:
            if project.id == pid:
                return project  # already registered

        project = RegisteredProject(id=pid, name=name or root.name, path=str(root))
        projects.append(project)
        self._write(projects)
        return project

    def remove(self, id: str) -> bool:
        """Deregister the project with this id; never touches the project files.

        Returns True when a project was removed, False when the id was unknown.
        """
        projects = self._read()
        remaining = [p for p in projects if p.id != id]
        if len(remaining) == len(projects):
            return False
        self._write(remaining)
        return True
