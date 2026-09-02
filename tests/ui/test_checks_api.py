# test_checks_api.py — GET /checks/history and GET /checks/audit: thin routes
# over checks.check_history / checks.audit_checks.
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write_log(runs_dir: Path, stem: str, events: list[dict]) -> Path:
    """Write one run-log .jsonl file with the given event dicts, one per line."""
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"{stem}.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return path


def _check_finished(name: str, passed: bool, duration_s: float | None = None) -> dict:
    event = {"event": "check_finished", "attempt": 0, "name": name, "passed": passed}
    if duration_s is not None:
        event["duration_s"] = duration_s
    return event


# ---------------------------------------------------------------------------
# GET /checks/history
# ---------------------------------------------------------------------------


class TestChecksHistory:
    def test_no_run_logs_yet_is_an_empty_list(self, client, registered: str) -> None:
        resp = client.get(f"/api/projects/{registered}/checks/history")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_mixed_pass_fail_reports_pass_rate_and_flake_score(
        self, client, registered: str, project: Path
    ) -> None:
        runs_dir = project / ".alc" / "runs"
        _write_log(
            runs_dir,
            "20260101T000000-task-a-aaaaaa",
            [
                _check_finished("test", True, 1.0),
                _check_finished("test", False, 3.0),
            ],
        )

        resp = client.get(f"/api/projects/{registered}/checks/history")
        assert resp.status_code == 200
        [entry] = resp.json()
        assert entry == {
            "name": "test",
            "runs": 2,
            "passes": 1,
            "pass_rate": 0.5,
            "mean_duration_s": 2.0,
            "flake_score": 1.0,
        }

    def test_multiple_checks_are_aggregated_separately(
        self, client, registered: str, project: Path
    ) -> None:
        runs_dir = project / ".alc" / "runs"
        _write_log(
            runs_dir,
            "20260101T000000-task-a-aaaaaa",
            [_check_finished("lint", True), _check_finished("test", False)],
        )

        resp = client.get(f"/api/projects/{registered}/checks/history")
        names = {entry["name"] for entry in resp.json()}
        assert names == {"lint", "test"}


# ---------------------------------------------------------------------------
# GET /checks/audit
# ---------------------------------------------------------------------------


class TestChecksAudit:
    def test_no_stack_detected_still_audits_the_security_set(
        self, client, registered: str
    ) -> None:
        resp = client.get(f"/api/projects/{registered}/checks/audit")
        assert resp.status_code == 200
        body = resp.json()
        assert any(cs["set_name"] == "security" for cs in body["check_sets"])
        # With no stack, the scaffold's smoke-only blueprints are now flagged too
        # (stacks == [] means "no stack detected") — the gap that needs it most.
        names = {b["blueprint"] for b in body["smoke_only_blueprints"]}
        assert names == {"bug", "chore", "feature"}
        assert all(b["stacks"] == [] for b in body["smoke_only_blueprints"])

    def test_detected_stack_proposes_a_new_check_set(
        self, client, registered: str, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("alc.checks.shutil.which", lambda cmd: f"/usr/bin/{cmd}")
        (project / "pyproject.toml").write_text("[project]\nname='x'\n")

        resp = client.get(f"/api/projects/{registered}/checks/audit")
        assert resp.status_code == 200
        body = resp.json()
        python_set = next(cs for cs in body["check_sets"] if cs["set_name"] == "python")
        assert python_set["is_new"] is True
        assert {name for name, _cmd in python_set["add"]} == {"test", "lint"}
        assert python_set["unavailable"] == []

    def test_binary_missing_reports_unavailable(
        self, client, registered: str, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("alc.checks.shutil.which", lambda cmd: None)
        (project / "pyproject.toml").write_text("[project]\nname='x'\n")

        resp = client.get(f"/api/projects/{registered}/checks/audit")
        body = resp.json()
        python_set = next(cs for cs in body["check_sets"] if cs["set_name"] == "python")
        assert python_set["add"] == []
        assert {name for name, _cmd in python_set["unavailable"]} == {"test", "lint"}

    def test_smoke_only_blueprints_flagged_when_stack_detected(
        self, client, registered: str, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("alc.checks.shutil.which", lambda cmd: None)
        (project / "pyproject.toml").write_text("[project]\nname='x'\n")

        resp = client.get(f"/api/projects/{registered}/checks/audit")
        body = resp.json()
        names = {b["blueprint"] for b in body["smoke_only_blueprints"]}
        # `plan` keeps the smoke placeholder by design — never flagged.
        assert names == {"bug", "chore", "feature"}
        assert all(b["stacks"] == ["Python"] for b in body["smoke_only_blueprints"])
