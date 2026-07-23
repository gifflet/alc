# test_queue_api.py — Queue endpoints: enqueue, list, delete pending, retry.
from __future__ import annotations

from pathlib import Path

from alc.models import FlowReport, RunReport, Scorecard


def _write_failed_archive(project: Path, stem: str, task: str = "do the thing") -> None:
    """Write a failed done/ task + report so retry has something to re-enqueue."""
    done = project / ".alc" / "queue" / "done"
    done.mkdir(parents=True, exist_ok=True)
    (done / f"{stem}.yaml").write_text(
        f"flow: ship\ntask: {task!r}\nengine: mock\nisolate: false\n"
    )
    report = FlowReport(
        flow="ship",
        engine="mock",
        success=False,
        stages=[
            RunReport(
                blueprint="chore",
                engine="mock",
                success=False,
                attempts=[],
                scorecard=Scorecard(span=0, passes=1, streak=0, touch=0),
                output_text="check failed: boom",
            )
        ],
        scorecard=Scorecard(span=0, passes=1, streak=0, touch=0),
    )
    (done / f"{stem}.report.json").write_text(report.model_dump_json(indent=2))


def _write_success_retry(project: Path, stem: str, retry_of: str) -> None:
    """Write a SUCCESSFUL retry archive that resolves the ``retry_of`` lineage."""
    done = project / ".alc" / "queue" / "done"
    done.mkdir(parents=True, exist_ok=True)
    (done / f"{stem}.yaml").write_text(
        "flow: ship\ntask: 'do the thing'\nengine: mock\nisolate: false\n"
        f"retries: 1\nretry_of: {retry_of}\n"
    )
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
            )
        ],
        scorecard=Scorecard(span=1, passes=1, streak=1, touch=0),
    )
    (done / f"{stem}.report.json").write_text(report.model_dump_json(indent=2))


class TestOutstandingFlag:
    def test_read_queue_marks_only_outstanding_failures(
        self, client, registered: str, project: Path
    ) -> None:
        # Unresolved failure -> retryable (outstanding).
        _write_failed_archive(project, "alone")
        # Resolved lineage: an original failure fixed by a later successful retry
        # -> the original failure is NOT outstanding (retrying it is a no-op).
        _write_failed_archive(project, "orig")
        _write_success_retry(project, "retry1", retry_of="orig")

        done = client.get(f"/api/projects/{registered}/queue").json()["done"]
        by = {d["stem"]: d for d in done}
        assert by["alone"]["outstanding"] is True
        assert by["orig"]["outstanding"] is False
        assert by["retry1"]["outstanding"] is False


class TestPendingOrder:
    """read_queue()'s `pending` list mirrors the drain's real dispatch order
    (queue.py's `_topological_waves`): `(-priority, stem)`."""

    def _write_pending(self, project: Path, stem: str, priority: int = 0) -> None:
        queue = project / ".alc" / "queue"
        queue.mkdir(parents=True, exist_ok=True)
        (queue / f"{stem}.yaml").write_text(
            f"flow: ship\ntask: 'x'\nengine: mock\nisolate: false\npriority: {priority}\n"
        )

    def test_higher_priority_written_later_sorts_first(
        self, client, registered: str, project: Path
    ) -> None:
        self._write_pending(project, "alpha")  # written first, default priority
        self._write_pending(project, "zzz-late", priority=5)  # written later, higher priority

        pending = client.get(f"/api/projects/{registered}/queue").json()["pending"]
        assert [p["stem"] for p in pending] == ["zzz-late", "alpha"]

    def test_default_priority_preserves_name_order(
        self, client, registered: str, project: Path
    ) -> None:
        self._write_pending(project, "b-task")
        self._write_pending(project, "a-task")

        pending = client.get(f"/api/projects/{registered}/queue").json()["pending"]
        assert [p["stem"] for p in pending] == ["a-task", "b-task"]


class TestEnqueue:
    def test_enqueue_creates_pending_task(self, client, registered: str, project: Path) -> None:
        resp = client.post(
            f"/api/projects/{registered}/queue",
            json={"flow": "ship", "task": "tidy the repo", "engine": "mock", "isolate": False},
        )
        assert resp.status_code == 201
        stem = resp.json()["stem"]
        assert (project / ".alc" / "queue" / f"{stem}.yaml").exists()

        pending = client.get(f"/api/projects/{registered}/queue").json()["pending"]
        assert len(pending) == 1
        assert pending[0]["stem"] == stem
        assert pending[0]["task"]["task"] == "tidy the repo"

    def test_enqueue_invalid_is_422(self, client, registered: str) -> None:
        # QueueTask requires 'task'.
        resp = client.post(f"/api/projects/{registered}/queue", json={"flow": "ship"})
        assert resp.status_code == 422


class TestDeletePending:
    def test_delete_pending(self, client, registered: str, project: Path) -> None:
        stem = client.post(
            f"/api/projects/{registered}/queue",
            json={"flow": "ship", "task": "x", "isolate": False},
        ).json()["stem"]

        resp = client.delete(f"/api/projects/{registered}/queue/{stem}")
        assert resp.status_code == 204
        assert not (project / ".alc" / "queue" / f"{stem}.yaml").exists()

    def test_delete_missing_is_404(self, client, registered: str) -> None:
        assert client.delete(f"/api/projects/{registered}/queue/ghost").status_code == 404


class TestDoneListing:
    def test_done_carries_task_and_report(self, client, registered: str, project: Path) -> None:
        _write_failed_archive(project, "job-1")
        done = client.get(f"/api/projects/{registered}/queue").json()["done"]
        assert len(done) == 1
        assert done[0]["stem"] == "job-1"
        assert done[0]["report"]["success"] is False
        assert done[0]["task"]["flow"] == "ship"


class TestRetry:
    def test_retry_single_stem(self, client, registered: str, project: Path) -> None:
        _write_failed_archive(project, "job-1")
        resp = client.post(
            f"/api/projects/{registered}/queue/retry", json={"stem": "job-1"}
        )
        assert resp.status_code == 200
        enqueued = resp.json()["enqueued"]
        assert len(enqueued) == 1
        # The re-enqueued task lands as a new pending file carrying the feedback.
        pending_file = project / ".alc" / "queue" / f"{enqueued[0]}.yaml"
        assert pending_file.exists()
        assert "Previous attempt failed" in pending_file.read_text()

    def test_retry_all(self, client, registered: str, project: Path) -> None:
        _write_failed_archive(project, "job-1", task="alpha")
        _write_failed_archive(project, "job-2", task="beta")
        resp = client.post(f"/api/projects/{registered}/queue/retry", json={"all": True})
        assert resp.status_code == 200
        assert len(resp.json()["enqueued"]) == 2

    def test_retry_unknown_stem_is_404(self, client, registered: str) -> None:
        resp = client.post(
            f"/api/projects/{registered}/queue/retry", json={"stem": "ghost"}
        )
        assert resp.status_code == 404

    def test_retry_without_target_is_400(self, client, registered: str) -> None:
        resp = client.post(f"/api/projects/{registered}/queue/retry", json={})
        assert resp.status_code == 400
