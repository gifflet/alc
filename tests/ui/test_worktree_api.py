# test_worktree_api.py — service.worktree_status + GET /worktree.
#
# `client`/`registered`/`project` come from conftest.py (a non-git scaffolded
# project); the git-backed cases layer a real LOCAL repo on top, mirroring the
# house style (tests/test_branches_api.py / tests/test_commitmsg.py). The endpoint
# backs the Loops view's reassuring dirty-tree notice AND the StatusBar's live
# branch/ahead-behind cluster: an autonomous run is safe on a dirty tree (it
# commits only what it produces), so the UI warns and proceeds — this endpoint
# tells it whether to show that banner and what the repo currently looks like.
#
# The shape is the enriched RepoStatus (asdict): `dirty` stays a backward-
# compatible key (semantically identical to has_non_alc_changes) alongside
# branch/upstream/ahead/behind/untracked. ahead/behind come ONLY from the local
# tracking ref (as of the last fetch) — the endpoint NEVER fetches.
from __future__ import annotations

import subprocess
from pathlib import Path

from alc.ui import service


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _git_init(repo: Path) -> None:
    """Turn an already-scaffolded project into a git repo with one seed commit.

    The seed `git add -A` commits everything the scaffold wrote, so the tree is
    CLEAN immediately after — each test then dirties (or not) exactly what it means to.
    """
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.email", "test@alc.local")
    _git(repo, "config", "user.name", "ALC Test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")


def _local_remote(repo: Path, remote_dir: Path) -> None:
    """Give *repo* a LOCAL bare remote and push main -u (upstream set, no network)."""
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote_dir)],
        check=True,
        capture_output=True,
    )
    _git(repo, "remote", "add", "origin", str(remote_dir))
    _git(repo, "push", "-u", "origin", "main")


# ---------------------------------------------------------------------------
# service.worktree_status — the enriched RepoStatus wrapper (asdict)
# ---------------------------------------------------------------------------


class TestWorktreeStatusService:
    def test_dirty_true_when_a_non_alc_file_is_uncommitted(self, project: Path) -> None:
        _git_init(project)
        (project / "src.py").write_text("print('wip')\n")  # uncommitted, outside .alc/

        status = service.worktree_status(project)
        assert status["available"] is True
        assert status["dirty"] is True
        assert status["branch"] == "main"

    def test_dirty_false_on_a_clean_tree(self, project: Path) -> None:
        _git_init(project)  # seed commit lands everything -> tree is clean

        status = service.worktree_status(project)
        assert status["available"] is True
        assert status["dirty"] is False
        assert status["untracked"] == 0

    def test_alc_only_change_does_not_count_as_dirty(self, project: Path) -> None:
        _git_init(project)
        # A change confined to .alc/ (control-plane state) never blocks a run.
        (project / ".alc" / "scratch.txt").write_text("control-plane churn\n")

        assert service.worktree_status(project)["dirty"] is False

    def test_off_git_is_unavailable_and_not_dirty(self, project: Path) -> None:
        # The scaffolded project is NOT a git repo -> available False, and no repo
        # means no WIP to protect, so dirty is a graceful False, never an error.
        (project / "src.py").write_text("print('wip')\n")

        status = service.worktree_status(project)
        assert status["available"] is False
        assert status["dirty"] is False
        assert status["branch"] is None

    def test_local_remote_surfaces_branch_and_ahead(self, project: Path) -> None:
        _git_init(project)
        _local_remote(project, project.parent / "remote.git")
        # One unpushed commit -> ahead=1 straight off the local tracking ref
        # (as of the push). We NEVER fetch to compute this.
        (project / "more.py").write_text("x = 1\n")
        _git(project, "add", "-A")
        _git(project, "commit", "-m", "more")

        status = service.worktree_status(project)
        assert status["branch"] == "main"
        assert status["upstream"] == "origin/main"
        assert status["ahead"] == 1
        assert status["behind"] == 0
        assert status["untracked"] == 0

    def test_no_upstream_leaves_ahead_behind_null(self, project: Path) -> None:
        _git_init(project)  # a repo with a branch but no remote -> no upstream

        status = service.worktree_status(project)
        assert status["upstream"] is None
        assert status["ahead"] is None
        assert status["behind"] is None


# ---------------------------------------------------------------------------
# GET /api/projects/{id}/worktree — the thin route over the service
# ---------------------------------------------------------------------------


class TestWorktreeRoute:
    def test_returns_200_with_the_shape_off_git(self, client, registered: str) -> None:
        resp = client.get(f"/api/projects/{registered}/worktree")
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is False
        assert body["dirty"] is False
        # The full enriched shape is always present (server always sends them).
        for key in ("branch", "detached", "upstream", "ahead", "behind", "untracked"):
            assert key in body

    def test_reports_dirty_true_for_an_uncommitted_non_alc_file(
        self, client, registered: str, project: Path
    ) -> None:
        _git_init(project)
        (project / "src.py").write_text("print('wip')\n")

        resp = client.get(f"/api/projects/{registered}/worktree")
        assert resp.status_code == 200
        body = resp.json()
        assert body["dirty"] is True
        assert body["available"] is True

    def test_reports_dirty_false_on_a_clean_tree(
        self, client, registered: str, project: Path
    ) -> None:
        _git_init(project)

        resp = client.get(f"/api/projects/{registered}/worktree")
        assert resp.status_code == 200
        assert resp.json()["dirty"] is False

    def test_reports_branch_and_ahead_for_a_local_remote(
        self, client, registered: str, project: Path
    ) -> None:
        _git_init(project)
        _local_remote(project, project.parent / "remote.git")
        (project / "more.py").write_text("x = 1\n")
        _git(project, "add", "-A")
        _git(project, "commit", "-m", "more")

        resp = client.get(f"/api/projects/{registered}/worktree")
        assert resp.status_code == 200
        body = resp.json()
        assert body["branch"] == "main"
        assert body["ahead"] == 1
        assert body["behind"] == 0
        assert body["upstream"] == "origin/main"

    def test_no_upstream_reports_nulls(
        self, client, registered: str, project: Path
    ) -> None:
        _git_init(project)

        resp = client.get(f"/api/projects/{registered}/worktree")
        assert resp.status_code == 200
        body = resp.json()
        assert body["upstream"] is None
        assert body["ahead"] is None
        assert body["behind"] is None
