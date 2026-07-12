# test_api_write.py — Mutating per-project endpoints (manifest, collections, prompts).
from __future__ import annotations

from pathlib import Path


class TestManifestWrite:
    def test_put_valid_manifest(self, client, registered: str, project: Path) -> None:
        raw = (project / ".alc" / "manifest.yaml").read_text()
        updated = raw.replace("plan_tier: standard", "").rstrip() + "\ndefault_timeout_s: 900\n"
        resp = client.put(f"/api/projects/{registered}/manifest", json={"raw": updated})
        assert resp.status_code == 200
        assert resp.json()["parsed"]["default_timeout_s"] == 900
        assert (project / ".alc" / "manifest.yaml").read_text() == updated

    def test_put_invalid_yaml_is_422_and_not_written(
        self, client, registered: str, project: Path
    ) -> None:
        before = (project / ".alc" / "manifest.yaml").read_text()
        resp = client.put(
            f"/api/projects/{registered}/manifest", json={"raw": "default_engine: [oops\n"}
        )
        assert resp.status_code == 422
        assert (project / ".alc" / "manifest.yaml").read_text() == before

    def test_put_manifest_with_lint_error_is_422(
        self, client, registered: str, project: Path
    ) -> None:
        before = (project / ".alc" / "manifest.yaml").read_text()
        # default_engine points at an engine that is not declared -> Policy Gate error.
        bad = before.replace("default_engine: mock", "default_engine: ghost")
        resp = client.put(f"/api/projects/{registered}/manifest", json={"raw": bad})
        assert resp.status_code == 422
        assert "violations" in resp.json()
        assert (project / ".alc" / "manifest.yaml").read_text() == before


class TestBlueprintWrite:
    def test_put_valid_blueprint_updates_file(
        self, client, registered: str, project: Path
    ) -> None:
        body = client.get(f"/api/projects/{registered}/blueprints/chore").json()
        new_raw = body["raw"].replace(
            "Apply a low-risk", "Apply a very low-risk"
        )
        resp = client.put(
            f"/api/projects/{registered}/blueprints/chore", json={"raw": new_raw}
        )
        assert resp.status_code == 200
        assert resp.json()["parsed"]["purpose"].startswith("Apply a very low-risk")
        assert "very low-risk" in (project / ".alc" / "blueprints" / "chore.md").read_text()

    def test_put_invalid_blueprint_is_422_and_not_written(
        self, client, registered: str, project: Path
    ) -> None:
        path = project / ".alc" / "blueprints" / "chore.md"
        before = path.read_text()
        # A check declaring BOTH command and shell fails the Check validator.
        bad = (
            "---\nname: chore\npurpose: x\nchecks:\n"
            '  - name: c\n    command: ["true"]\n    shell: "true"\n---\nbody\n'
        )
        resp = client.put(
            f"/api/projects/{registered}/blueprints/chore", json={"raw": bad}
        )
        assert resp.status_code == 422
        assert path.read_text() == before

    def test_post_creates_blueprint(self, client, registered: str, project: Path) -> None:
        raw = (
            "---\nname: docs\npurpose: Update documentation.\n"
            "checks:\n  - name: smoke\n    command: [\"true\"]\n---\n# Docs\n"
        )
        resp = client.post(
            f"/api/projects/{registered}/blueprints",
            json={"name": "docs", "raw": raw},
        )
        assert resp.status_code == 201
        assert (project / ".alc" / "blueprints" / "docs.md").exists()

    def test_post_existing_is_409(self, client, registered: str) -> None:
        raw = "---\nname: chore\npurpose: x\nchecks:\n  - name: c\n    command: [\"true\"]\n---\nb\n"
        resp = client.post(
            f"/api/projects/{registered}/blueprints", json={"name": "chore", "raw": raw}
        )
        assert resp.status_code == 409

    def test_delete_blueprint(self, client, registered: str, project: Path) -> None:
        resp = client.delete(f"/api/projects/{registered}/blueprints/bug")
        assert resp.status_code == 204
        assert not (project / ".alc" / "blueprints" / "bug.md").exists()

    def test_delete_missing_is_404(self, client, registered: str) -> None:
        assert client.delete(f"/api/projects/{registered}/blueprints/ghost").status_code == 404


class TestScaffoldCreate:
    """POST with an empty raw scaffolds a minimal, valid unit for the collection."""

    def test_create_blueprint_scaffold(self, client, registered: str, project: Path) -> None:
        resp = client.post(
            f"/api/projects/{registered}/blueprints", json={"name": "docs"}
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["parsed"]["name"] == "docs"
        assert body["parsed"]["checks"]
        assert (project / ".alc" / "blueprints" / "docs.md").exists()

    def test_create_flow_scaffold(self, client, registered: str, project: Path) -> None:
        resp = client.post(f"/api/projects/{registered}/flows", json={"name": "review"})
        assert resp.status_code == 201
        assert resp.json()["parsed"]["name"] == "review"
        assert (project / ".alc" / "flows" / "review.yaml").exists()

    def test_create_specialist_scaffold(self, client, registered: str) -> None:
        resp = client.post(
            f"/api/projects/{registered}/specialists", json={"name": "api"}
        )
        assert resp.status_code == 201
        assert resp.json()["parsed"]["blueprint"] == "chore"

    def test_create_loop_scaffold(self, client, registered: str) -> None:
        resp = client.post(f"/api/projects/{registered}/loops", json={"name": "nightly"})
        assert resp.status_code == 201
        assert resp.json()["parsed"]["stop"]["max_cycles"] > 0

    def test_create_primer_scaffold(self, client, registered: str, project: Path) -> None:
        resp = client.post(f"/api/projects/{registered}/primers", json={"name": "house"})
        assert resp.status_code == 201
        assert (project / ".alc" / "primers" / "house.md").exists()

    def test_create_free_prompt_scaffold(self, client, registered: str, project: Path) -> None:
        resp = client.post(f"/api/projects/{registered}/prompts", json={"name": "style"})
        assert resp.status_code == 201
        assert (project / ".alc" / "prompts" / "style.md").read_text().strip()


class TestPromptWrite:
    def test_put_reserved_override(self, client, registered: str, project: Path) -> None:
        # A valid override keeps the required {failures} placeholder.
        resp = client.put(
            f"/api/projects/{registered}/prompts/repair",
            json={"raw": "Custom repair. Fix:\n{failures}\n"},
        )
        assert resp.status_code == 200
        assert resp.json()["ejected"] is True
        assert (project / ".alc" / "prompts" / "repair.md").exists()

    def test_put_reserved_override_missing_placeholder_is_422(
        self, client, registered: str, project: Path
    ) -> None:
        resp = client.put(
            f"/api/projects/{registered}/prompts/repair",
            json={"raw": "No placeholder here.\n"},
        )
        assert resp.status_code == 422
        assert not (project / ".alc" / "prompts" / "repair.md").exists()

    def test_post_free_prompt(self, client, registered: str, project: Path) -> None:
        resp = client.post(
            f"/api/projects/{registered}/prompts",
            json={"name": "house-style", "raw": "Follow the house style.\n"},
        )
        assert resp.status_code == 201
        assert (project / ".alc" / "prompts" / "house-style.md").exists()

    def test_post_reserved_name_is_409(self, client, registered: str) -> None:
        resp = client.post(
            f"/api/projects/{registered}/prompts", json={"name": "repair", "raw": "x"}
        )
        assert resp.status_code == 409

    def test_delete_non_ejected_reserved_is_409(self, client, registered: str) -> None:
        resp = client.delete(f"/api/projects/{registered}/prompts/repair")
        assert resp.status_code == 409

    def test_delete_ejected_reserved_ok(self, client, registered: str, project: Path) -> None:
        client.put(
            f"/api/projects/{registered}/prompts/repair",
            json={"raw": "Custom.\n{failures}\n"},
        )
        resp = client.delete(f"/api/projects/{registered}/prompts/repair")
        assert resp.status_code == 204
        assert not (project / ".alc" / "prompts" / "repair.md").exists()
