# test_review_api.py — Diff review: read a branch's change, send notes back as work.
#
# The load-bearing properties: a GET never writes, an empty review is refused,
# and the notes become exactly ONE queue task whose body carries every comment
# anchored to path:line.
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import yaml

from alc.ui.review import compose_feedback


def git(project: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)


def repo_with_branch(project: Path, branch: str = "alc/run-a1b2c3d4") -> None:
    git(project, "init", "-q")
    git(project, "config", "user.email", "t@example.com")
    git(project, "config", "user.name", "t")
    (project / "app.py").write_text("def f():\n    return 1\n")
    git(project, "add", "-A")
    git(project, "commit", "-qm", "seed")
    git(project, "checkout", "-qb", branch)
    (project / "app.py").write_text("def f():\n    return 2\n")
    git(project, "add", "-A")
    git(project, "commit", "-qm", "change")
    git(project, "checkout", "-q", "-")


class TestComposeFeedback:
    def test_anchors_every_comment_to_path_and_line(self) -> None:
        body = compose_feedback(
            "alc/run-a1b2c3d4",
            [
                {"path": "src/foo.py", "line": 42, "text": "this drops the None guard; keep it."},
                {"path": "src/bar.py", "line": 17, "text": "extract this into the existing helper."},
            ],
        )
        assert body.startswith("Review feedback on branch alc/run-a1b2c3d4:")
        assert "src/foo.py:42 — this drops the None guard; keep it." in body
        assert "src/bar.py:17 — extract this into the existing helper." in body

    def test_tolerates_a_comment_with_no_line(self) -> None:
        body = compose_feedback("alc/x", [{"path": "README.md", "text": "stale section"}])
        assert "README.md — stale section" in body


class TestBranchDiff:
    def test_returns_the_branch_change(self, client, registered: str, project: Path) -> None:
        repo_with_branch(project)
        resp = client.get(
            f"/api/projects/{registered}/branches/diff", params={"branch": "alc/run-a1b2c3d4"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["branch"] == "alc/run-a1b2c3d4"
        assert "return 2" in body["diff"]

    def test_rejects_a_non_alc_branch(self, client, registered: str, project: Path) -> None:
        repo_with_branch(project)
        resp = client.get(
            f"/api/projects/{registered}/branches/diff", params={"branch": "main"}
        )
        assert resp.status_code == 422

    def test_reading_a_diff_writes_nothing(self, client, registered: str, project: Path) -> None:
        repo_with_branch(project)

        def snapshot() -> list[tuple[str, str]]:
            return sorted(
                (p.relative_to(project).as_posix(), hashlib.sha256(p.read_bytes()).hexdigest())
                for p in (project / ".alc").rglob("*")
                if p.is_file()
            )

        before = snapshot()
        client.get(f"/api/projects/{registered}/branches/diff", params={"branch": "alc/run-a1b2c3d4"})
        assert snapshot() == before


class TestSubmitReview:
    def body(self, **over) -> dict:
        payload = {
            "branch": "alc/run-a1b2c3d4",
            "comments": [
                {"path": "app.py", "line": 2, "text": "keep returning 1"},
                {"path": "app.py", "line": 5, "text": "add a test for this"},
            ],
            "kind": "flow",
            "name": "ship",
        }
        payload.update(over)
        return payload

    def test_creates_exactly_one_task_carrying_every_comment(
        self, client, registered: str, project: Path
    ) -> None:
        repo_with_branch(project)
        resp = client.post(f"/api/projects/{registered}/branches/review", json=self.body())
        assert resp.status_code == 200, resp.text
        assert resp.json()["comments"] == 2

        pending = list((project / ".alc" / "queue").glob("*.yaml"))
        assert len(pending) == 1, "the reviewer's notes are ONE unit of work"
        task = yaml.safe_load(pending[0].read_text())
        assert "app.py:2 — keep returning 1" in task["task"]
        assert "app.py:5 — add a test for this" in task["task"]
        assert task["name"] == "ship"

    def test_refuses_an_empty_review(self, client, registered: str, project: Path) -> None:
        repo_with_branch(project)
        resp = client.post(
            f"/api/projects/{registered}/branches/review", json=self.body(comments=[])
        )
        assert resp.status_code == 422
        assert not list((project / ".alc" / "queue").glob("*.yaml"))

    def test_refuses_comments_that_are_only_whitespace(
        self, client, registered: str, project: Path
    ) -> None:
        repo_with_branch(project)
        resp = client.post(
            f"/api/projects/{registered}/branches/review",
            json=self.body(comments=[{"path": "app.py", "line": 2, "text": "   "}]),
        )
        assert resp.status_code == 422

    def test_rejects_a_non_alc_branch(self, client, registered: str, project: Path) -> None:
        repo_with_branch(project)
        resp = client.post(
            f"/api/projects/{registered}/branches/review", json=self.body(branch="main")
        )
        assert resp.status_code == 422

    def test_refuses_a_review_with_no_unit_to_run_as(
        self, client, registered: str, project: Path
    ) -> None:
        # QueueTask.unit_name() would resolve to "" and the drain could never
        # dispatch it: a task that cannot run must never reach the queue.
        repo_with_branch(project)
        resp = client.post(
            f"/api/projects/{registered}/branches/review", json=self.body(name=None)
        )
        assert resp.status_code == 422
        assert "unit to run as" in resp.json()["detail"]
        assert not list((project / ".alc" / "queue").glob("*.yaml"))

    def test_the_queued_task_names_a_dispatchable_unit(
        self, client, registered: str, project: Path
    ) -> None:
        repo_with_branch(project)
        client.post(f"/api/projects/{registered}/branches/review", json=self.body())
        task = yaml.safe_load(next((project / ".alc" / "queue").glob("*.yaml")).read_text())
        # Both fields carry it, so old and new readers resolve the same unit.
        assert task["name"] == "ship"
        assert task["flow"] == "ship"

    def test_the_queued_task_is_a_normal_unit(self, client, registered: str, project: Path) -> None:
        # It must drain like anything else: same file shape, same validation.
        repo_with_branch(project)
        client.post(f"/api/projects/{registered}/branches/review", json=self.body())
        queue = client.get(f"/api/projects/{registered}/queue").json()
        assert len(queue["pending"]) == 1
