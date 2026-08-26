# test_inbox_api.py — GET /inbox: the decisions waiting on a human.
#
# The Inbox must agree with `alc retry` about what is outstanding (it reuses
# queue.outstanding_failures), must never write, and must count exactly what it
# lists — the badge and the list come from one number.
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import yaml

from alc.models import AttemptRecord, FlowReport, QueueTask, RunReport, Scorecard


def _report(success: bool, *, blueprint: str = "chore", failed: list[str] | None = None) -> FlowReport:
    """A FlowReport shaped like a real archive, so _failure_reason reads it."""
    card = Scorecard(span=1, passes=1 if success else 0, streak=1 if success else 0, touch=0)
    stage = RunReport(
        blueprint=blueprint,
        engine="mock",
        success=success,
        attempts=[AttemptRecord(index=0, engine_ok=True, failed_checks=failed or [])],
        scorecard=card,
        output_text="",
    )
    return FlowReport(flow="ship", engine="mock", success=success, stages=[stage], scorecard=card)


def archive(project: Path, stem: str, *, success: bool, task: str, retry_of: str | None = None,
            retries: int = 0, failed: list[str] | None = None) -> None:
    """Write a done/<stem>.yaml + .report.json pair, as the drain does."""
    done = project / ".alc" / "queue" / "done"
    done.mkdir(parents=True, exist_ok=True)
    qt = QueueTask(kind="flow", name="ship", task=task, retry_of=retry_of, retries=retries)
    (done / f"{stem}.yaml").write_text(yaml.safe_dump(qt.model_dump(mode="json")))
    (done / f"{stem}.report.json").write_text(_report(success, failed=failed).model_dump_json())


def git(project: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)


def make_repo_with_branch(project: Path, branch: str) -> None:
    """A real git repo with one unmerged `alc/*` branch."""
    git(project, "init", "-q")
    git(project, "config", "user.email", "t@example.com")
    git(project, "config", "user.name", "t")
    (project / "seed.txt").write_text("seed\n")
    git(project, "add", "-A")
    git(project, "commit", "-qm", "seed")
    git(project, "checkout", "-qb", branch)
    (project / "work.txt").write_text("work\n")
    git(project, "add", "-A")
    git(project, "commit", "-qm", "work")
    git(project, "checkout", "-q", "-")


class TestInbox:
    def test_zero_state(self, client, registered: str) -> None:
        body = client.get(f"/api/projects/{registered}/inbox").json()
        assert body == {"items": [], "count": 0}

    def test_lists_an_outstanding_failure_with_its_reason(
        self, client, registered: str, project: Path
    ) -> None:
        archive(project, "v1-01-impl-aaa", success=False, task="add the changelog entry",
                failed=["pytest"])

        body = client.get(f"/api/projects/{registered}/inbox").json()
        assert body["count"] == 1
        item = body["items"][0]
        assert item["kind"] == "failure"
        assert item["title"] == "add the changelog entry"
        # The reason must name the gate, not be free text.
        assert "pytest" in item["reason"]
        assert item["stem"] == "v1-01-impl-aaa"

    def test_hides_a_failure_already_resolved_by_a_later_retry(
        self, client, registered: str, project: Path
    ) -> None:
        # Same lineage: the retry succeeded, so nothing needs a human.
        archive(project, "v1-01-impl-aaa", success=False, task="add the changelog entry")
        archive(project, "v1-01-impl-bbb", success=True, task="add the changelog entry",
                retry_of="v1-01-impl-aaa", retries=1)

        body = client.get(f"/api/projects/{registered}/inbox").json()
        assert body["count"] == 0

    def test_lists_an_unmerged_branch_as_ready_to_land(
        self, client, registered: str, project: Path
    ) -> None:
        make_repo_with_branch(project, "alc/run-a1b2c3d4")

        items = client.get(f"/api/projects/{registered}/inbox").json()["items"]
        branches = [i for i in items if i["kind"] == "branch"]
        assert len(branches) == 1
        assert branches[0]["branch"] == "alc/run-a1b2c3d4"
        assert "land" in branches[0]["reason"]

    def test_lists_a_loop_stopped_by_a_backstop(
        self, client, registered: str, project: Path
    ) -> None:
        loops = project / ".alc" / "loops"
        loops.mkdir(parents=True, exist_ok=True)
        (loops / "sweep.yaml").write_text(
            yaml.safe_dump({"name": "sweep", "stop": {"max_cycles": 5},
                            "replenish": {"kind": "flow", "name": "ship"}})
        )
        (loops / "sweep.state.json").write_text(
            json.dumps({"name": "sweep", "status": "stopped", "cycle": 7,
                        "stopped_reason": "budget exhausted: usd"})
        )

        items = client.get(f"/api/projects/{registered}/inbox").json()["items"]
        loop_items = [i for i in items if i["kind"] == "loop"]
        assert len(loop_items) == 1
        assert loop_items[0]["loop"] == "sweep"
        assert loop_items[0]["reason"] == "budget exhausted: usd"
        assert loop_items[0]["cycle"] == 7

    def test_a_running_loop_is_not_a_decision(
        self, client, registered: str, project: Path
    ) -> None:
        loops = project / ".alc" / "loops"
        loops.mkdir(parents=True, exist_ok=True)
        (loops / "sweep.yaml").write_text(
            yaml.safe_dump({"name": "sweep", "stop": {"max_cycles": 5},
                            "replenish": {"kind": "flow", "name": "ship"}})
        )
        (loops / "sweep.state.json").write_text(
            json.dumps({"name": "sweep", "status": "running", "cycle": 2})
        )
        assert client.get(f"/api/projects/{registered}/inbox").json()["count"] == 0

    def test_failures_outrank_branches(self, client, registered: str, project: Path) -> None:
        make_repo_with_branch(project, "alc/run-a1b2c3d4")
        archive(project, "v1-01-impl-aaa", success=False, task="broken thing")

        kinds = [i["kind"] for i in client.get(f"/api/projects/{registered}/inbox").json()["items"]]
        assert kinds.index("failure") < kinds.index("branch")

    def test_count_matches_the_list_exactly(self, client, registered: str, project: Path) -> None:
        make_repo_with_branch(project, "alc/run-a1b2c3d4")
        archive(project, "v1-01-impl-aaa", success=False, task="broken thing")

        body = client.get(f"/api/projects/{registered}/inbox").json()
        # The badge must never drift from what the list shows.
        assert body["count"] == len(body["items"])

    def test_is_read_only(self, client, registered: str, project: Path) -> None:
        archive(project, "v1-01-impl-aaa", success=False, task="broken thing")

        def snapshot() -> list[tuple[str, str]]:
            return sorted(
                (p.relative_to(project).as_posix(), hashlib.sha256(p.read_bytes()).hexdigest())
                for p in (project / ".alc").rglob("*")
                if p.is_file()
            )

        before = snapshot()
        client.get(f"/api/projects/{registered}/inbox")
        assert snapshot() == before

    def test_degrades_outside_a_git_repo(self, client, registered: str) -> None:
        # No git repo: branches simply contribute nothing — never a 500.
        assert client.get(f"/api/projects/{registered}/inbox").status_code == 200

    def test_unknown_project_is_404(self, client) -> None:
        assert client.get("/api/projects/ghost/inbox").status_code == 404


class TestRetryPending:
    """A queued retry does not resolve a failure — but must be visible."""

    def test_a_failure_starts_without_a_pending_retry(
        self, client, registered: str, project: Path
    ) -> None:
        archive(project, "v1-01-impl-aaa", success=False, task="broken thing")
        item = client.get(f"/api/projects/{registered}/inbox").json()["items"][0]
        assert item["retry_pending"] is False

    def test_a_queued_retry_marks_the_failure_without_removing_it(
        self, client, registered: str, project: Path
    ) -> None:
        archive(project, "v1-01-impl-aaa", success=False, task="broken thing")
        # What `alc retry` writes: a pending task pointing at the lineage root.
        queue = project / ".alc" / "queue"
        queue.mkdir(parents=True, exist_ok=True)
        qt = QueueTask(kind="flow", name="ship", task="broken thing",
                       retry_of="v1-01-impl-aaa", retries=1)
        (queue / "retry-01-broken-thing-abc.yaml").write_text(
            yaml.safe_dump(qt.model_dump(mode="json"))
        )

        body = client.get(f"/api/projects/{registered}/inbox").json()
        # Still outstanding: only a SUCCESSFUL run resolves it.
        assert body["count"] == 1
        assert body["items"][0]["retry_pending"] is True

    def test_a_retry_for_a_different_lineage_does_not_mark_this_one(
        self, client, registered: str, project: Path
    ) -> None:
        archive(project, "v1-01-impl-aaa", success=False, task="broken thing")
        queue = project / ".alc" / "queue"
        queue.mkdir(parents=True, exist_ok=True)
        qt = QueueTask(kind="flow", name="ship", task="other", retry_of="unrelated-stem", retries=1)
        (queue / "retry-01-other-xyz.yaml").write_text(yaml.safe_dump(qt.model_dump(mode="json")))

        assert client.get(f"/api/projects/{registered}/inbox").json()["items"][0]["retry_pending"] is False

    def test_follows_the_lineage_root_not_the_latest_stem(
        self, client, registered: str, project: Path
    ) -> None:
        # Attempt 2 failed; the retry that produced it points at the root, and a
        # further retry would too — so matching on the latest stem alone misses it.
        archive(project, "v1-01-impl-aaa", success=False, task="broken thing")
        archive(project, "v1-01-impl-bbb", success=False, task="broken thing",
                retry_of="v1-01-impl-aaa", retries=1)
        queue = project / ".alc" / "queue"
        queue.mkdir(parents=True, exist_ok=True)
        qt = QueueTask(kind="flow", name="ship", task="broken thing",
                       retry_of="v1-01-impl-aaa", retries=2)
        (queue / "retry-02-broken-thing-def.yaml").write_text(
            yaml.safe_dump(qt.model_dump(mode="json"))
        )

        body = client.get(f"/api/projects/{registered}/inbox").json()
        assert body["count"] == 1
        assert body["items"][0]["stem"] == "v1-01-impl-bbb"
        assert body["items"][0]["retry_pending"] is True


class TestInboxResilience:
    def test_one_malformed_loop_does_not_hide_another_loop_halt(
        self, client, registered: str, project: Path
    ) -> None:
        loops = project / ".alc" / "loops"
        loops.mkdir(parents=True, exist_ok=True)
        # A YAML typo in one loop must not silence the Inbox for the others.
        (loops / "broken.yaml").write_text("name: [unclosed\n")
        (loops / "sweep.yaml").write_text(
            yaml.safe_dump({"name": "sweep", "stop": {"max_cycles": 5}})
        )
        (loops / "sweep.state.json").write_text(
            json.dumps({"name": "sweep", "status": "stopped", "cycle": 3,
                        "stopped_reason": "max_cycles reached"})
        )

        items = client.get(f"/api/projects/{registered}/inbox").json()["items"]
        assert [i["loop"] for i in items if i["kind"] == "loop"] == ["sweep"]

    def test_a_loop_without_state_yet_is_not_a_decision(
        self, client, registered: str, project: Path
    ) -> None:
        loops = project / ".alc" / "loops"
        loops.mkdir(parents=True, exist_ok=True)
        (loops / "fresh.yaml").write_text(
            yaml.safe_dump({"name": "fresh", "stop": {"max_cycles": 5}})
        )
        assert client.get(f"/api/projects/{registered}/inbox").json()["count"] == 0
