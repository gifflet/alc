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

    def test_hire_duplicate_without_force_is_an_additive_no_op(
        self, client, registered: str, project: Path
    ) -> None:
        # Additive hire never conflicts (no 409): a second hire of a fully-present
        # pack writes nothing and reports every file as kept.
        first = client.post(
            f"/api/projects/{registered}/team/hire", json={"archetype": "builder"}
        )
        assert first.status_code == 201
        all_files = first.json()["written"]

        second = client.post(
            f"/api/projects/{registered}/team/hire", json={"archetype": "builder"}
        )
        assert second.status_code == 201
        body = second.json()
        assert body["written"] == []
        assert sorted(body["kept"]) == sorted(all_files)

    def test_hire_partial_writes_only_the_missing_file(
        self, client, registered: str, project: Path
    ) -> None:
        # A partially-present pack (one file deleted) receives ONLY that file back.
        first = client.post(
            f"/api/projects/{registered}/team/hire", json={"archetype": "builder"}
        )
        assert first.status_code == 201

        removed = project / ".alc" / "blueprints" / "qa.md"
        removed.unlink()

        resp = client.post(
            f"/api/projects/{registered}/team/hire", json={"archetype": "builder"}
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["written"] == [".alc/blueprints/qa.md"]
        assert ".alc/blueprints/test.md" in body["kept"]
        assert removed.is_file()

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


class TestRetire:
    def test_retire_unknown_archetype_is_404(self, client, registered: str) -> None:
        resp = client.post(
            f"/api/projects/{registered}/team/retire", json={"archetype": "nosuchpack"}
        )
        assert resp.status_code == 404
        assert "nosuchpack" in resp.json()["detail"]

    def test_retire_a_member_with_no_loops_is_a_no_op(
        self, client, registered: str
    ) -> None:
        client.post(f"/api/projects/{registered}/team/hire", json={"archetype": "builder"})

        resp = client.post(
            f"/api/projects/{registered}/team/retire", json={"archetype": "builder"}
        )
        assert resp.status_code == 200
        assert resp.json() == {"moved": []}

    def test_retire_archives_the_loop_and_it_leaves_the_rosters_live_files(
        self, client, registered: str, project: Path
    ) -> None:
        hired = client.post(
            f"/api/projects/{registered}/team/hire", json={"archetype": "sweeper"}
        )
        assert hired.status_code == 201

        resp = client.post(
            f"/api/projects/{registered}/team/retire", json={"archetype": "sweeper"}
        )
        assert resp.status_code == 200
        assert resp.json() == {"moved": [".alc/loops/retired/sweep.yaml"]}

        assert not (project / ".alc" / "loops" / "sweep.yaml").exists()
        assert (project / ".alc" / "loops" / "retired" / "sweep.yaml").is_file()

        # Only the loop moved — the pack's other files (blueprints, specialist,
        # flow) are untouched, so the member stays in the roster with fewer live
        # files; ".alc/loops/sweep.yaml" itself no longer exists on disk.
        roster = client.get(f"/api/projects/{registered}/team").json()
        sweeper = next(m for m in roster["members"] if m["archetype"] == "sweeper")
        assert ".alc/loops/sweep.yaml" not in sweeper["files"]
        assert ".alc/specialists/janitor.yaml" in sweeper["files"]

    def test_retire_publishes_a_loop_changed_ws_event(
        self, client, registered: str
    ) -> None:
        client.post(f"/api/projects/{registered}/team/hire", json={"archetype": "sweeper"})

        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "subscribe", "project_id": registered})
            assert ws.receive_json()["type"] == "subscribed"

            resp = client.post(
                f"/api/projects/{registered}/team/retire", json={"archetype": "sweeper"}
            )
            assert resp.status_code == 200

            message = ws.receive_json()
            assert message["type"] == "loop_changed"
            assert message["name"] == "sweep"


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

    def test_idle_core_hints_exercising_a_hired_but_unexercised_archetype(
        self, client, registered: str, project: Path
    ) -> None:
        # /team must carry the idle-core hint the CLI shows — one computation,
        # both surfaces. maintainer is hired (brought deps-refresh) but idle.
        manifest_path = project / ".alc" / "manifest.yaml"
        manifest_path.write_text(manifest_path.read_text() + "\nstage: strong-pmf\n")
        client.post(
            f"/api/projects/{registered}/team/hire", json={"archetype": "maintainer"}
        )
        _write_archive(project, "r1", archetype="sweeper")  # so total_runs > 0

        body = client.get(f"/api/projects/{registered}/team").json()
        idle = {e["archetype"]: e for e in body["mix_health"]["idle_core"]}
        assert idle["maintainer"]["hired"] is True
        assert idle["maintainer"]["hint"] == "run its loop (alc loop deps-refresh)"


class TestRemove:
    def test_remove_unknown_archetype_is_404(self, client, registered: str) -> None:
        resp = client.post(
            f"/api/projects/{registered}/team/remove", json={"archetype": "nosuchpack"}
        )
        assert resp.status_code == 404
        assert "nosuchpack" in resp.json()["detail"]

    def test_remove_a_fresh_pack_takes_it_off_the_roster(
        self, client, registered: str, project: Path
    ) -> None:
        client.post(f"/api/projects/{registered}/team/hire", json={"archetype": "sweeper"})

        resp = client.post(
            f"/api/projects/{registered}/team/remove", json={"archetype": "sweeper"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["kept"] == []
        assert ".alc/loops/sweep.yaml" in body["removed"]

        roster = client.get(f"/api/projects/{registered}/team").json()
        assert all(m["archetype"] != "sweeper" for m in roster["members"])
        assert not (project / ".alc" / "blueprints" / "map.md").exists()

    def test_remove_keeps_a_customised_file_and_the_member(
        self, client, registered: str, project: Path
    ) -> None:
        client.post(f"/api/projects/{registered}/team/hire", json={"archetype": "sweeper"})
        blueprint = project / ".alc" / "blueprints" / "map.md"
        blueprint.write_text(blueprint.read_text() + "\ncustom\n")

        resp = client.post(
            f"/api/projects/{registered}/team/remove", json={"archetype": "sweeper"}
        )
        assert resp.status_code == 200
        assert resp.json()["kept"] == [".alc/blueprints/map.md"]
        assert blueprint.exists()

        roster = client.get(f"/api/projects/{registered}/team").json()
        sweeper = next(m for m in roster["members"] if m["archetype"] == "sweeper")
        assert sweeper["files"] == [".alc/blueprints/map.md"]

    def test_roster_reports_a_retired_loop(self, client, registered: str) -> None:
        client.post(f"/api/projects/{registered}/team/hire", json={"archetype": "sweeper"})
        client.post(f"/api/projects/{registered}/team/retire", json={"archetype": "sweeper"}
        )

        roster = client.get(f"/api/projects/{registered}/team").json()
        sweeper = next(m for m in roster["members"] if m["archetype"] == "sweeper")
        assert sweeper["loops"] == []
        assert sweeper["retired_loops"] == ["sweep"]

    def test_remove_publishes_the_same_ws_events_a_hire_does(
        self, client, registered: str
    ) -> None:
        client.post(f"/api/projects/{registered}/team/hire", json={"archetype": "builder"})

        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "subscribe", "project_id": registered})
            assert ws.receive_json()["type"] == "subscribed"

            resp = client.post(
                f"/api/projects/{registered}/team/remove", json={"archetype": "builder"}
            )
            assert resp.status_code == 200

            # Same classifier, same file set as the hire that wrote them —
            # so the roster and project tree refresh through the events they
            # already know.
            messages = [ws.receive_json() for _ in range(2)]
            kinds = {(m["type"], m.get("resource")) for m in messages}
            assert ("config_changed", "blueprints") in kinds
            assert ("config_changed", "flows") in kinds
