# test_api_read.py — Read-only per-project endpoints.
from __future__ import annotations

from pathlib import Path


class TestManifest:
    def test_get_manifest_raw_and_parsed(self, client, registered: str) -> None:
        resp = client.get(f"/api/projects/{registered}/manifest")
        assert resp.status_code == 200
        body = resp.json()
        assert "default_engine: mock" in body["raw"]
        assert body["parsed"]["default_engine"] == "mock"
        assert "standard" in body["parsed"]["compute_tiers"]

    def test_unknown_project_is_404(self, client) -> None:
        assert client.get("/api/projects/ghost/manifest").status_code == 404


class TestCollections:
    def test_list_blueprints(self, client, registered: str) -> None:
        resp = client.get(f"/api/projects/{registered}/blueprints")
        assert resp.status_code == 200
        names = {item["name"] for item in resp.json()}
        assert {"chore", "bug", "feature", "plan"} <= names

    def test_get_blueprint_raw_and_parsed(self, client, registered: str) -> None:
        resp = client.get(f"/api/projects/{registered}/blueprints/chore")
        assert resp.status_code == 200
        body = resp.json()
        assert body["parsed"]["name"] == "chore"
        assert body["parsed"]["checks"]
        assert "Chore Workflow" in body["raw"]

    def test_get_missing_blueprint_is_404(self, client, registered: str) -> None:
        assert client.get(f"/api/projects/{registered}/blueprints/nope").status_code == 404

    def test_list_flows_and_get(self, client, registered: str) -> None:
        listed = client.get(f"/api/projects/{registered}/flows").json()
        assert {item["name"] for item in listed} == {"ship"}
        ship = client.get(f"/api/projects/{registered}/flows/ship").json()
        assert ship["parsed"]["name"] == "ship"
        assert len(ship["parsed"]["stages"]) == 2

    def test_unknown_collection_is_404(self, client, registered: str) -> None:
        assert client.get(f"/api/projects/{registered}/bogus").status_code == 404

    def test_primers_empty_by_default(self, client, registered: str) -> None:
        assert client.get(f"/api/projects/{registered}/primers").json() == []


class TestPrompts:
    def test_list_prompts_marks_reserved(self, client, registered: str) -> None:
        entries = client.get(f"/api/projects/{registered}/prompts").json()
        by_name = {e["name"]: e for e in entries}
        assert by_name["repair"]["reserved"] is True
        assert by_name["repair"]["ejected"] is False

    def test_get_reserved_prompt_resolves_default(self, client, registered: str) -> None:
        body = client.get(f"/api/projects/{registered}/prompts/repair").json()
        assert body["reserved"] is True
        assert body["ejected"] is False
        assert "Repair Required" in body["raw"]

    def test_get_unknown_prompt_is_404(self, client, registered: str) -> None:
        assert client.get(f"/api/projects/{registered}/prompts/ghost").status_code == 404


class TestQueueRunsEmpty:
    def test_queue_empty(self, client, registered: str) -> None:
        body = client.get(f"/api/projects/{registered}/queue").json()
        assert body == {"pending": [], "done": []}

    def test_runs_empty(self, client, registered: str) -> None:
        body = client.get(f"/api/projects/{registered}/runs").json()
        assert body == {"runs": [], "total": 0}

    def test_scorecard_zeroed(self, client, registered: str) -> None:
        body = client.get(f"/api/projects/{registered}/scorecard").json()
        assert body["reports"] == 0
        assert body["successes"] == 0


class TestRunsFinished:
    """The runs list's ``finished`` flag must agree with the run detail: a
    flow/task run's inner ``mandate_finished`` is NOT terminal — the run stays
    live until ``flow_finished`` / ``task_finished``; a bare mandate run closes
    at its own ``mandate_finished``."""

    def _write_run(self, project: Path, stem: str, events: list[str]) -> None:
        runs = project / ".alc" / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        body = "".join(f'{{"event": "{e}"}}\n' for e in events)
        (runs / f"{stem}.jsonl").write_text(body)

    def test_finished_flag_matches_run_kind(
        self, client, registered: str, project: Path
    ) -> None:
        # A flow still mid-flight: its last stage's mandate finished, but no
        # flow_finished yet → the list must NOT call it finished.
        self._write_run(
            project,
            "20260101T000000-flow-live-aaaaaa",
            ["flow_started", "stage_started", "mandate_started", "mandate_finished"],
        )
        # A flow that reached flow_finished → finished.
        self._write_run(
            project,
            "20260101T000001-flow-done-bbbbbb",
            ["flow_started", "mandate_started", "mandate_finished", "flow_finished"],
        )
        # A task that reached task_finished → finished.
        self._write_run(
            project,
            "20260101T000002-task-done-cccccc",
            ["task_started", "mandate_started", "mandate_finished", "task_finished"],
        )
        # A bare mandate run (no flow/task wrapper) closes at mandate_finished.
        self._write_run(
            project,
            "20260101T000003-run-bare-dddddd",
            ["mandate_started", "mandate_finished"],
        )

        runs = client.get(f"/api/projects/{registered}/runs").json()["runs"]
        finished = {r["stem"]: r["finished"] for r in runs}

        assert finished["20260101T000000-flow-live-aaaaaa"] is False
        assert finished["20260101T000001-flow-done-bbbbbb"] is True
        assert finished["20260101T000002-task-done-cccccc"] is True
        assert finished["20260101T000003-run-bare-dddddd"] is True

    def test_stale_flag_marks_an_interrupted_run(
        self, client, registered: str, project: Path
    ) -> None:
        import os
        import time

        runs = project / ".alc" / "runs"
        # An interrupted flow (no terminal event) whose log went quiet a day ago —
        # well past any turn timeout — has no live process behind it: stale.
        self._write_run(
            project,
            "20260101T000010-flow-interrupted-eeeeee",
            ["flow_started", "stage_started", "mandate_started"],
        )
        day_ago = time.time() - 24 * 3600
        os.utime(runs / "20260101T000010-flow-interrupted-eeeeee.jsonl", (day_ago, day_ago))
        # A freshly written unfinished run is live (not stale); a finished run is
        # never stale regardless of age.
        self._write_run(
            project, "20260101T000011-flow-live-ffffff", ["flow_started", "mandate_started"]
        )
        self._write_run(
            project, "20260101T000012-flow-done-gggggg", ["flow_started", "flow_finished"]
        )

        by = {
            r["stem"]: r
            for r in client.get(f"/api/projects/{registered}/runs").json()["runs"]
        }
        assert by["20260101T000010-flow-interrupted-eeeeee"]["stale"] is True
        assert by["20260101T000010-flow-interrupted-eeeeee"]["finished"] is False
        assert by["20260101T000011-flow-live-ffffff"]["stale"] is False
        assert by["20260101T000012-flow-done-gggggg"]["stale"] is False


class TestLintAndEngines:
    def test_lint_scaffolded_project_has_no_errors(self, client, registered: str) -> None:
        body = client.get(f"/api/projects/{registered}/lint").json()
        errors = [v for v in body["violations"] if v["severity"] == "error"]
        assert errors == []

    def test_engines_reports_mock_default_and_health(self, client, registered: str) -> None:
        engines = client.get(f"/api/projects/{registered}/engines").json()
        by_name = {e["name"]: e for e in engines}
        assert by_name["mock"]["default"] is True
        assert by_name["mock"]["healthy"] is True
        assert by_name["mock"]["tiers"] == {"standard": "mock-small", "deep": "mock-large"}


class TestLoops:
    def test_loop_state_defaults_to_pending(self, client, registered: str) -> None:
        body = client.get(f"/api/projects/{registered}/loops/deliver/state").json()
        assert body["name"] == "deliver"
        assert body["status"] == "pending"

    def test_loop_ledger_empty(self, client, registered: str) -> None:
        body = client.get(f"/api/projects/{registered}/loops/deliver/ledger").json()
        assert body == {"records": []}
