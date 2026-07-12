# test_run_configs.py — Command schema endpoint + run-config CRUD and validation.
from __future__ import annotations

import json
from pathlib import Path


class TestCommandSchema:
    def test_schema_exposes_expected_keys(self, client) -> None:
        schema = client.get("/api/commands").json()
        # `run` and `loop` carry the params from the command whitelist.
        assert schema["run"] == {
            "positionals": ["blueprint", "task"],
            "opt_positionals": [],
            "value_flags": ["engine", "tier", "primer"],
            "bool_flags": ["isolate", "bundle"],
        }
        assert schema["loop"] == {
            "positionals": ["name"],
            "opt_positionals": [],
            "value_flags": ["engine", "interval"],
            "bool_flags": ["reset"],
        }

    def test_schema_is_app_level_no_project_needed(self, client) -> None:
        assert client.get("/api/commands").status_code == 200


class TestRunConfigCrud:
    def test_round_trip_create_list_update_delete(
        self, client, registered: str, project: Path
    ) -> None:
        cfg = {
            "name": "ship it",
            "command": "run",
            "args": {"blueprint": "chore", "task": "tidy"},
        }
        resp = client.post(f"/api/projects/{registered}/run-configs", json=cfg)
        assert resp.status_code == 201
        assert resp.json() == cfg

        # The config is persisted to .alc/ui/run-configs.json.
        path = project / ".alc" / "ui" / "run-configs.json"
        assert path.exists()
        assert json.loads(path.read_text()) == {"configs": [cfg]}

        listed = client.get(f"/api/projects/{registered}/run-configs").json()
        assert listed == {"configs": [cfg]}

        updated = {
            "name": "ship it",
            "command": "run",
            "args": {"blueprint": "chore", "task": "tidy up", "isolate": True},
        }
        resp = client.put(
            f"/api/projects/{registered}/run-configs/ship%20it", json=updated
        )
        assert resp.status_code == 200
        assert resp.json() == updated
        assert json.loads(path.read_text()) == {"configs": [updated]}

        resp = client.delete(f"/api/projects/{registered}/run-configs/ship%20it")
        assert resp.status_code == 204
        assert client.get(f"/api/projects/{registered}/run-configs").json() == {
            "configs": []
        }


class TestRunConfigValidation:
    def test_bad_command_is_422(self, client, registered: str) -> None:
        resp = client.post(
            f"/api/projects/{registered}/run-configs",
            json={"name": "x", "command": "rm", "args": {}},
        )
        assert resp.status_code == 422

    def test_unknown_arg_is_422(self, client, registered: str) -> None:
        resp = client.post(
            f"/api/projects/{registered}/run-configs",
            json={"name": "x", "command": "run", "args": {"blueprint": "chore", "task": "t", "evil": "1"}},
        )
        assert resp.status_code == 422

    def test_missing_positional_is_422(self, client, registered: str) -> None:
        resp = client.post(
            f"/api/projects/{registered}/run-configs",
            json={"name": "x", "command": "run", "args": {"blueprint": "chore"}},
        )
        assert resp.status_code == 422

    def test_duplicate_name_is_409(self, client, registered: str) -> None:
        cfg = {"name": "dup", "command": "lint", "args": {}}
        assert client.post(f"/api/projects/{registered}/run-configs", json=cfg).status_code == 201
        assert client.post(f"/api/projects/{registered}/run-configs", json=cfg).status_code == 409

    def test_update_unknown_name_is_404(self, client, registered: str) -> None:
        resp = client.put(
            f"/api/projects/{registered}/run-configs/ghost",
            json={"name": "ghost", "command": "lint", "args": {}},
        )
        assert resp.status_code == 404

    def test_delete_unknown_name_is_404(self, client, registered: str) -> None:
        assert client.delete(f"/api/projects/{registered}/run-configs/ghost").status_code == 404


class TestMalformedFile:
    def test_malformed_file_is_tolerated(
        self, client, registered: str, project: Path
    ) -> None:
        path = project / ".alc" / "ui" / "run-configs.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ this is not valid json")

        resp = client.get(f"/api/projects/{registered}/run-configs")
        assert resp.status_code == 200
        assert resp.json() == {"configs": []}
