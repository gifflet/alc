# test_fleet_api.py — GET /fleet: the runs executing right now.
#
# "Active" must mean exactly what the Runs list already means (unfinished AND
# not stale), and the endpoint must hand back raw events — the fold into display
# state belongs to the frontend's buildTimeline, not to this backend.
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from alc.ui import service


def write_run(project: Path, stem: str, events: list[dict], *, age_s: float = 0.0) -> Path:
    """Write a run log; `age_s` backdates its mtime to simulate an idle log."""
    runs_dir = project / ".alc" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"{stem}.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in events))
    if age_s:
        old = time.time() - age_s
        import os

        os.utime(path, (old, old))
    return path


ACTIVE = [
    {"ts": "2026-08-25T10:00:00Z", "event": "mandate_started", "blueprint": "chore", "task": "tidy", "engine": "mock", "model": "m"},
    {"ts": "2026-08-25T10:00:01Z", "event": "act_started", "attempt": 0},
]
FINISHED = ACTIVE + [
    {"ts": "2026-08-25T10:00:02Z", "event": "act_finished", "attempt": 0, "ok": True},
    {"ts": "2026-08-25T10:00:03Z", "event": "mandate_finished", "success": True, "attempts": 1},
]


class TestFleet:
    def test_returns_only_unfinished_runs(self, client, registered: str, project: Path) -> None:
        write_run(project, "20260825T100000-run-chore-live-aaa", ACTIVE)
        write_run(project, "20260825T090000-run-chore-done-bbb", FINISHED)

        resp = client.get(f"/api/projects/{registered}/fleet")
        assert resp.status_code == 200
        stems = [u["stem"] for u in resp.json()["units"]]
        assert stems == ["20260825T100000-run-chore-live-aaa"]

    def test_excludes_a_stale_run(self, client, registered: str, project: Path) -> None:
        # Unfinished, but its log went quiet long ago: no process is writing it.
        write_run(project, "20260825T080000-run-chore-stale-ccc", ACTIVE, age_s=60 * 60 * 24)

        resp = client.get(f"/api/projects/{registered}/fleet")
        assert resp.json()["units"] == []

    def test_hands_back_raw_events_for_the_client_to_fold(
        self, client, registered: str, project: Path
    ) -> None:
        write_run(project, "20260825T100000-run-chore-live-aaa", ACTIVE)

        unit = client.get(f"/api/projects/{registered}/fleet").json()["units"][0]
        assert [e["event"] for e in unit["events"]] == ["mandate_started", "act_started"]
        assert unit["kind"] == "run"
        assert unit["truncated"] is False

    def test_caps_a_runaway_log_keeping_the_newest_events(
        self, client, registered: str, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(service, "FLEET_MAX_EVENTS", 3)
        noisy = ACTIVE + [
            {"ts": "2026-08-25T10:00:02Z", "event": "engine_activity", "note": f"step {i}"}
            for i in range(10)
        ]
        write_run(project, "20260825T100000-run-chore-noisy-ddd", noisy)

        unit = client.get(f"/api/projects/{registered}/fleet").json()["units"][0]
        assert unit["truncated"] is True
        assert len(unit["events"]) == 3
        # The TAIL is what matters: current phase, attempt, running check.
        assert unit["events"][-1]["note"] == "step 9"

    def test_empty_when_nothing_is_running(self, client, registered: str) -> None:
        assert client.get(f"/api/projects/{registered}/fleet").json() == {"units": []}

    def test_unknown_project_is_404(self, client) -> None:
        assert client.get("/api/projects/ghost/fleet").status_code == 404

    def test_is_read_only(self, client, registered: str, project: Path) -> None:
        write_run(project, "20260825T100000-run-chore-live-aaa", ACTIVE)
        before = sorted(
            (p.relative_to(project).as_posix(), p.stat().st_size)
            for p in (project / ".alc").rglob("*")
            if p.is_file()
        )
        client.get(f"/api/projects/{registered}/fleet")
        after = sorted(
            (p.relative_to(project).as_posix(), p.stat().st_size)
            for p in (project / ".alc").rglob("*")
            if p.is_file()
        )
        assert before == after
