# test_team_api.py — Team roster, hire, and Mix Health endpoints.
from __future__ import annotations

from pathlib import Path

from alc.engine import Usage
from alc.models import FlowReport, RunReport, Scorecard


def _write_archive(
    project: Path, stem: str, *, archetype: str | None, cost_usd: float = 0.0
) -> None:
    """Write a minimal archived report bucketed under *archetype*."""
    done = project / ".alc" / "queue" / "done"
    done.mkdir(parents=True, exist_ok=True)
    report = FlowReport(
        flow="ship",
        engine="mock",
        success=True,
        stages=[
            RunReport(
                blueprint="chore",
                engine="mock",
                success=True,
                attempts=[],
                scorecard=Scorecard(span=1, passes=1, streak=1, touch=0),
                output_text="all checks passed",
                archetype=archetype,
                usage=Usage(cost_usd=cost_usd),
            )
        ],
        scorecard=Scorecard(span=1, passes=1, streak=1, touch=0),
    )
    (done / f"{stem}.report.json").write_text(report.model_dump_json(indent=2))


class TestRosterEmpty:
    def test_no_members_hired_yet(self, client, registered: str) -> None:
        body = client.get(f"/api/projects/{registered}/team").json()
        assert body["members"] == []

    def test_mix_health_with_zero_archived_runs_signals_no_data(
        self, client, registered: str
    ) -> None:
        body = client.get(f"/api/projects/{registered}/team").json()
        health = body["mix_health"]
        assert health["total_runs"] == 0
        assert health["by_archetype"] == []


class TestHire:
    def test_hire_writes_the_pack_files(self, client, registered: str, project: Path) -> None:
        resp = client.post(
            f"/api/projects/{registered}/team/hire", json={"archetype": "builder"}
        )
        assert resp.status_code == 201
        body = resp.json()
        assert ".alc/blueprints/test.md" in body["written"]
        assert ".alc/blueprints/qa.md" in body["written"]
        assert ".alc/flows/ship-hardened.yaml" in body["written"]
        assert (project / ".alc" / "blueprints" / "test.md").is_file()
        assert (project / ".alc" / "flows" / "ship-hardened.yaml").is_file()
        assert body["lint"]["violations"] == [] or all(
            v["severity"] != "error" for v in body["lint"]["violations"]
        )

    def test_hired_member_appears_in_the_roster(
        self, client, registered: str, project: Path
    ) -> None:
        client.post(f"/api/projects/{registered}/team/hire", json={"archetype": "builder"})

        body = client.get(f"/api/projects/{registered}/team").json()
        assert len(body["members"]) == 1
        member = body["members"][0]
        assert member["archetype"] == "builder"
        assert ".alc/blueprints/test.md" in member["files"]
        assert member["loops"] == []

    def test_hire_unknown_archetype_is_404(self, client, registered: str) -> None:
        resp = client.post(
            f"/api/projects/{registered}/team/hire", json={"archetype": "nosuchpack"}
        )
        assert resp.status_code == 404
        assert "nosuchpack" in resp.json()["detail"]

    def test_hire_duplicate_without_force_is_409(
        self, client, registered: str, project: Path
    ) -> None:
        first = client.post(
            f"/api/projects/{registered}/team/hire", json={"archetype": "builder"}
        )
        assert first.status_code == 201

        second = client.post(
            f"/api/projects/{registered}/team/hire", json={"archetype": "builder"}
        )
        assert second.status_code == 409

    def test_hire_with_force_overwrites(self, client, registered: str, project: Path) -> None:
        client.post(f"/api/projects/{registered}/team/hire", json={"archetype": "builder"})
        target = project / ".alc" / "blueprints" / "test.md"
        target.write_text("garbage")

        resp = client.post(
            f"/api/projects/{registered}/team/hire",
            json={"archetype": "builder", "force": True},
        )
        assert resp.status_code == 201
        assert "name: test" in target.read_text()

    def test_hire_publishes_a_collection_changed_ws_event(
        self, client, registered: str
    ) -> None:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "subscribe", "project_id": registered})
            assert ws.receive_json()["type"] == "subscribed"

            resp = client.post(
                f"/api/projects/{registered}/team/hire", json={"archetype": "builder"}
            )
            assert resp.status_code == 201

            messages = [ws.receive_json() for _ in range(2)]
            kinds = {(m["type"], m.get("resource")) for m in messages}
            assert ("config_changed", "blueprints") in kinds
            assert ("config_changed", "flows") in kinds


class TestMixHealth:
    def test_no_stage_declared_is_unjudged_breakdown(
        self, client, registered: str, project: Path
    ) -> None:
        _write_archive(project, "r1", archetype="builder")

        body = client.get(f"/api/projects/{registered}/team").json()
        health = body["mix_health"]
        assert health["stage"] is None
        assert health["core"] == []
        assert health["secondary"] == []
        assert health["total_runs"] == 1
        by_archetype = {e["archetype"]: e for e in health["by_archetype"]}
        assert by_archetype["builder"]["runs"] == 1

    def test_stage_declared_carries_the_target_mix(
        self, client, registered: str, project: Path
    ) -> None:
        manifest_path = project / ".alc" / "manifest.yaml"
        manifest_path.write_text(manifest_path.read_text() + "\nstage: growth\n")
        _write_archive(project, "r1", archetype="builder", cost_usd=0.5)

        body = client.get(f"/api/projects/{registered}/team").json()
        health = body["mix_health"]
        assert health["stage"] == "growth"
        assert health["core"] == ["builder", "sweeper", "grower"]
        assert health["secondary"] == ["maintainer"]
        assert health["total_runs"] == 1
        by_archetype = {e["archetype"]: e for e in health["by_archetype"]}
        assert by_archetype["builder"]["cost_usd"] == 0.5
