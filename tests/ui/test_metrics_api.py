# test_metrics_api.py — Metrics, artifacts (list + bytes) and audit endpoints
# (UI Phase 3 Wave 1: the measurement backend).
from __future__ import annotations

import json
import os
from pathlib import Path

from alc.metrics import append_measurement, ledger_path
from alc.models import FlowReport, MetricRecord, RunReport, Scorecard


def _record(
    check: str, value: float, ts: float, run: str = "r", passed: bool = True
) -> MetricRecord:
    return MetricRecord(check=check, value=value, ts=ts, run=run, passed=passed)


def _write_run_log(project: Path, stem: str, artifacts: list[str] | None = None) -> Path:
    """Write one run log with a single `mandate_finished` event."""
    runs_dir = project / ".alc" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    event = {"event": "mandate_finished", "success": True}
    if artifacts is not None:
        event["artifacts"] = artifacts
    path = runs_dir / f"{stem}.jsonl"
    path.write_text(json.dumps(event) + "\n")
    return path


def _write_archive(project: Path, stem: str, *, success: bool = True, span: int = 1) -> None:
    """Write one minimal archived FlowReport under queue/done."""
    done = project / ".alc" / "queue" / "done"
    done.mkdir(parents=True, exist_ok=True)
    report = FlowReport(
        flow="ship",
        engine="mock",
        success=success,
        stages=[
            RunReport(
                blueprint="chore",
                engine="mock",
                success=success,
                attempts=[],
                scorecard=Scorecard(span=span, passes=1, streak=1, touch=0),
                output_text="",
            )
        ],
        scorecard=Scorecard(span=span, passes=1, streak=1, touch=0),
    )
    (done / f"{stem}.report.json").write_text(report.model_dump_json())


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class TestMetrics:
    def test_empty_ledger_yields_empty_series(self, client, registered: str) -> None:
        body = client.get(f"/api/projects/{registered}/metrics").json()
        assert body == {}

    def test_populated_series_carries_delta_trend_and_passed(
        self, client, registered: str, project: Path
    ) -> None:
        path = ledger_path(project / ".alc" / "metrics")
        append_measurement(path, _record("bundle-size", 100.0, 1.0, run="ship"))
        append_measurement(path, _record("bundle-size", 110.0, 2.0, run="ship", passed=False))

        body = client.get(f"/api/projects/{registered}/metrics").json()
        points = body["bundle-size"]
        assert points[0] == {
            "ts": 1.0,
            "value": 100.0,
            "run": "ship",
            "delta": None,
            "trend": "n/a",
            "passed": True,
        }
        assert points[1]["delta"] == 10.0
        assert points[1]["trend"] == "up"
        assert points[1]["passed"] is False

    def test_check_query_param_scopes_the_series(
        self, client, registered: str, project: Path
    ) -> None:
        path = ledger_path(project / ".alc" / "metrics")
        append_measurement(path, _record("a", 1.0, 1.0))
        append_measurement(path, _record("b", 2.0, 2.0))

        body = client.get(
            f"/api/projects/{registered}/metrics", params={"check": "a"}
        ).json()
        assert set(body) == {"a"}


# ---------------------------------------------------------------------------
# Artifacts — list
# ---------------------------------------------------------------------------


class TestRunArtifactsList:
    def test_lists_paths_and_types(self, client, registered: str, project: Path) -> None:
        _write_run_log(
            project,
            "20260101T000000-task-a-aaaaaa",
            [".alc/artifacts/a/shot.png", ".alc/artifacts/a/health-poll.log"],
        )
        body = client.get(
            f"/api/projects/{registered}/runs/20260101T000000-task-a-aaaaaa/artifacts"
        ).json()
        assert body["stem"] == "20260101T000000-task-a-aaaaaa"
        assert body["artifacts"] == [
            {"path": ".alc/artifacts/a/shot.png", "type": "image"},
            {"path": ".alc/artifacts/a/health-poll.log", "type": "log"},
        ]

    def test_unknown_run_is_404(self, client, registered: str) -> None:
        resp = client.get(f"/api/projects/{registered}/runs/ghost/artifacts")
        assert resp.status_code == 404

    def test_known_run_with_no_artifacts_is_an_empty_list(
        self, client, registered: str, project: Path
    ) -> None:
        _write_run_log(project, "20260101T000000-task-a-aaaaaa")
        body = client.get(
            f"/api/projects/{registered}/runs/20260101T000000-task-a-aaaaaa/artifacts"
        ).json()
        assert body == {"stem": "20260101T000000-task-a-aaaaaa", "artifacts": []}


class TestLatestArtifacts:
    def test_no_run_has_captured_any_is_an_empty_result(
        self, client, registered: str
    ) -> None:
        resp = client.get(f"/api/projects/{registered}/artifacts")
        assert resp.status_code == 200
        assert resp.json() == {"stem": None, "artifacts": []}

    def test_picks_the_most_recently_modified_run_with_artifacts(
        self, client, registered: str, project: Path
    ) -> None:
        older = _write_run_log(project, "20260101T000000-task-a-aaaaaa", ["old.log"])
        newer = _write_run_log(project, "20260101T000001-task-b-bbbbbb", ["new.log"])
        now = 2_000_000_000.0
        os.utime(older, (now - 100, now - 100))
        os.utime(newer, (now, now))

        body = client.get(f"/api/projects/{registered}/artifacts").json()
        assert body == {
            "stem": "20260101T000001-task-b-bbbbbb",
            "artifacts": [{"path": "new.log", "type": "log"}],
        }


# ---------------------------------------------------------------------------
# Artifacts — bytes (the sensitive route: containment is a security boundary)
# ---------------------------------------------------------------------------


class TestArtifactBytes:
    """The bytes route resolves ``path`` against the PROJECT ROOT (the same
    base ``RunReport.artifacts`` paths are relative to, i.e.
    ``.alc/artifacts/<stem>/...``) — NOT against ``artifacts_dir`` directly —
    while still confining the resolved file to ``artifacts_dir``. This is what
    keeps it in agreement with the list routes below (see
    TestArtifactListAndBytesRoundTrip)."""

    def _write_artifact(self, project: Path, rel: str, content: bytes = b"hello") -> str:
        """Write a file under ``.alc/artifacts/<rel>``; return its project-root-relative path."""
        path = project / ".alc" / "artifacts" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return f".alc/artifacts/{rel}"

    def test_serves_a_file_inside_artifacts_dir(
        self, client, registered: str, project: Path
    ) -> None:
        rel_path = self._write_artifact(project, "run-1/shot.png", b"\x89PNGDATA")

        resp = client.get(
            f"/api/projects/{registered}/artifacts/file", params={"path": rel_path}
        )
        assert resp.status_code == 200
        assert resp.content == b"\x89PNGDATA"
        assert resp.headers["content-type"].startswith("image/png")

    def test_dotdot_traversal_is_rejected(
        self, client, registered: str, project: Path, tmp_path: Path
    ) -> None:
        (project / ".alc" / "artifacts").mkdir(parents=True, exist_ok=True)
        # Escapes the project entirely (project is `tmp_path/demo`).
        secret = tmp_path / "secret.txt"
        secret.write_text("do not serve me")

        resp = client.get(
            f"/api/projects/{registered}/artifacts/file",
            params={"path": "../secret.txt"},
        )
        assert resp.status_code == 403
        assert "do not serve me" not in resp.text

    def test_a_project_relative_path_outside_artifacts_dir_is_rejected(
        self, client, registered: str
    ) -> None:
        # Exists in the project (scaffold always writes it) but is not under
        # artifacts_dir -- resolving against the project root must NOT make
        # every project file fair game.
        resp = client.get(
            f"/api/projects/{registered}/artifacts/file",
            params={"path": ".alc/manifest.yaml"},
        )
        assert resp.status_code == 403

    def test_absolute_path_is_rejected(
        self, client, registered: str, project: Path, tmp_path: Path
    ) -> None:
        outside = tmp_path / "outside-secret.txt"
        outside.write_text("nope")
        (project / ".alc" / "artifacts").mkdir(parents=True, exist_ok=True)

        resp = client.get(
            f"/api/projects/{registered}/artifacts/file", params={"path": str(outside)}
        )
        assert resp.status_code == 403

    def test_symlink_escape_is_rejected(
        self, client, registered: str, project: Path, tmp_path: Path
    ) -> None:
        outside = tmp_path / "outside-secret.txt"
        outside.write_text("nope")
        artifacts_dir = project / ".alc" / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        (artifacts_dir / "escape.txt").symlink_to(outside)

        resp = client.get(
            f"/api/projects/{registered}/artifacts/file",
            params={"path": ".alc/artifacts/escape.txt"},
        )
        assert resp.status_code == 403

    def test_missing_file_inside_dir_is_404(
        self, client, registered: str, project: Path
    ) -> None:
        (project / ".alc" / "artifacts").mkdir(parents=True, exist_ok=True)

        resp = client.get(
            f"/api/projects/{registered}/artifacts/file",
            params={"path": ".alc/artifacts/ghost.log"},
        )
        assert resp.status_code == 404


class TestArtifactListAndBytesRoundTrip:
    """The `path` the list route emits must be exactly what the bytes route
    accepts -- neither endpoint hardcodes a path convention independently."""

    def test_a_path_from_the_list_endpoint_round_trips_through_the_bytes_endpoint(
        self, client, registered: str, project: Path
    ) -> None:
        stem = "20260101T000000-task-a-aaaaaa"
        # The real project-root-relative shape RunReport.artifacts stores.
        artifact_rel = f".alc/artifacts/{stem}/golden.html"
        artifact_file = project / artifact_rel
        artifact_file.parent.mkdir(parents=True, exist_ok=True)
        artifact_file.write_bytes(b"<html>golden</html>")
        _write_run_log(project, stem, [artifact_rel])

        listed = client.get(
            f"/api/projects/{registered}/runs/{stem}/artifacts"
        ).json()
        [entry] = listed["artifacts"]
        assert entry["path"] == artifact_rel  # sanity: still the raw report shape

        resp = client.get(
            f"/api/projects/{registered}/artifacts/file", params={"path": entry["path"]}
        )
        assert resp.status_code == 200
        assert resp.content == b"<html>golden</html>"


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


class TestAudit:
    def test_valid_window_aggregates_archived_reports(
        self, client, registered: str, project: Path
    ) -> None:
        _write_archive(project, "r1", success=True, span=3)

        body = client.get(
            f"/api/projects/{registered}/audit", params={"since": "7d"}
        ).json()
        assert body["tasks_total"] == 1
        assert body["tasks_ok"] == 1
        assert body["span_total"] == 3

    def test_empty_window_is_all_zero(self, client, registered: str) -> None:
        body = client.get(
            f"/api/projects/{registered}/audit", params={"since": "24h"}
        ).json()
        assert body["tasks_total"] == 0
        assert body["cost_usd_total"] == 0.0

    def test_bogus_since_is_422_not_a_traceback(
        self, client, registered: str
    ) -> None:
        resp = client.get(
            f"/api/projects/{registered}/audit", params={"since": "bogus"}
        )
        assert resp.status_code == 422
        assert "invalid --since value" in resp.json()["detail"]
