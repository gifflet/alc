# test_registry.py — ProjectRegistry class + /api/projects endpoints.
from __future__ import annotations

from pathlib import Path

import pytest

from alc.ui.errors import ApiError
from alc.ui.registry import ProjectRegistry, project_id


class TestProjectRegistryClass:
    def test_add_and_list(self, project: Path, registry_path: Path) -> None:
        registry = ProjectRegistry(registry_path)
        entry = registry.add(str(project))
        assert entry.name == "demo"
        assert entry.path == str(project.resolve())
        assert entry.id == project_id(project)

        listed = registry.list()
        assert [p.id for p in listed] == [entry.id]

    def test_add_is_idempotent(self, project: Path, registry_path: Path) -> None:
        registry = ProjectRegistry(registry_path)
        first = registry.add(str(project))
        second = registry.add(str(project))
        assert first.id == second.id
        assert len(registry.list()) == 1

    def test_add_rejects_missing_path(self, tmp_path: Path, registry_path: Path) -> None:
        registry = ProjectRegistry(registry_path)
        with pytest.raises(ApiError) as exc:
            registry.add(str(tmp_path / "nope"))
        assert exc.value.status == 400

    def test_add_rejects_non_alc_dir(self, tmp_path: Path, registry_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        registry = ProjectRegistry(registry_path)
        with pytest.raises(ApiError) as exc:
            registry.add(str(plain))
        assert exc.value.status == 400

    def test_remove(self, project: Path, registry_path: Path) -> None:
        registry = ProjectRegistry(registry_path)
        entry = registry.add(str(project))
        assert registry.remove(entry.id) is True
        assert registry.list() == []
        assert registry.remove(entry.id) is False

    def test_project_id_is_stable_across_instances(self, project: Path) -> None:
        assert project_id(project) == project_id(project)


class TestProjectsApi:
    def test_post_registers_and_get_lists(self, client, project: Path) -> None:
        resp = client.post("/api/projects", json={"path": str(project)})
        assert resp.status_code == 201
        summary = resp.json()
        assert summary["name"] == "demo"
        assert summary["default_engine"] == "mock"
        assert summary["queue_pending"] == 0
        assert summary["available"] is True

        listed = client.get("/api/projects").json()
        assert len(listed) == 1
        assert listed[0]["id"] == summary["id"]

    def test_post_with_custom_name(self, client, project: Path) -> None:
        resp = client.post("/api/projects", json={"path": str(project), "name": "Custom"})
        assert resp.status_code == 201
        assert resp.json()["name"] == "Custom"

    def test_post_invalid_path_is_400(self, client, tmp_path: Path) -> None:
        resp = client.post("/api/projects", json={"path": str(tmp_path / "ghost")})
        assert resp.status_code == 400
        assert "detail" in resp.json()

    def test_post_non_alc_dir_is_400(self, client, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        resp = client.post("/api/projects", json={"path": str(plain)})
        assert resp.status_code == 400

    def test_delete_deregisters(self, client, registered: str, project: Path) -> None:
        resp = client.delete(f"/api/projects/{registered}")
        assert resp.status_code == 204
        assert client.get("/api/projects").json() == []
        # The project files are untouched by deregistration.
        assert (project / ".alc" / "manifest.yaml").exists()

    def test_delete_unknown_is_404(self, client) -> None:
        assert client.delete("/api/projects/does-not-exist").status_code == 404
