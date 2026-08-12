# conftest.py — Hermetic fixtures for the UI backend tests.
#
# Projects are scaffolded with the real `alc` scaffolder into tmp_path and the
# registry path is injected, so no test touches the user's real ~/.alc.
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alc.scaffold import scaffold
from alc.ui.server import create_app


@pytest.fixture
def make_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Return a factory that scaffolds a fresh ALC project under tmp_path."""
    counter = {"n": 0}
    # Hermetic: `alc init` now probes PATH for a real engine CLI — never let the
    # host machine's claude/gemini leak into these fixtures, which promise a
    # mock-engine project.
    monkeypatch.setattr("alc.scaffold.detect_default_engine", lambda: "mock")

    def _make(name: str | None = None) -> Path:
        counter["n"] += 1
        root = tmp_path / (name or f"proj{counter['n']}")
        root.mkdir(parents=True, exist_ok=True)
        scaffold(root)
        return root

    return _make


@pytest.fixture
def project(make_project) -> Path:
    """A single scaffolded ALC project (mock engine by default)."""
    return make_project("demo")


@pytest.fixture
def registry_path(tmp_path: Path) -> Path:
    """A temporary registry file path (never the real ~/.alc)."""
    return tmp_path / "registry" / "projects.json"


@pytest.fixture
def app(registry_path: Path):
    """The FastAPI app with the file watcher disabled (tests drive the bus)."""
    return create_app(registry_path, enable_watch=False)


@pytest.fixture
def client(app):
    """A TestClient inside the app lifespan (binds the bus to the loop)."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def registered(client, project: Path) -> str:
    """Register ``project`` and return its project id."""
    resp = client.post("/api/projects", json={"path": str(project)})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]
