# test_worktree_api.py — service.worktree_status + GET /worktree.
#
# `client`/`registered`/`project` come from conftest.py (a non-git scaffolded
# project); the git-backed cases layer a real LOCAL repo on top, mirroring the
# house style (tests/test_branches_api.py / tests/test_commitmsg.py). The endpoint
# backs the Loops view's reassuring dirty-tree notice: an autonomous run is safe on
# a dirty tree (it commits only what it produces), so the UI warns and proceeds —
# this endpoint just tells it whether to show that banner.
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


# ---------------------------------------------------------------------------
# service.worktree_status — the pure predicate wrapper
# ---------------------------------------------------------------------------


class TestWorktreeStatusService:
    def test_dirty_true_when_a_non_alc_file_is_uncommitted(self, project: Path) -> None:
        _git_init(project)
        (project / "src.py").write_text("print('wip')\n")  # uncommitted, outside .alc/

        assert service.worktree_status(project) == {"dirty": True}

    def test_dirty_false_on_a_clean_tree(self, project: Path) -> None:
        _git_init(project)  # seed commit lands everything -> tree is clean

        assert service.worktree_status(project) == {"dirty": False}

    def test_alc_only_change_does_not_count_as_dirty(self, project: Path) -> None:
        _git_init(project)
        # A change confined to .alc/ (control-plane state) never blocks a run.
        (project / ".alc" / "scratch.txt").write_text("control-plane churn\n")

        assert service.worktree_status(project) == {"dirty": False}

    def test_dirty_false_off_git(self, project: Path) -> None:
        # The scaffolded project is NOT a git repo -> no repo means no WIP to
        # protect, so the guard is a graceful no-op (dirty False), never an error.
        (project / "src.py").write_text("print('wip')\n")

        assert service.worktree_status(project) == {"dirty": False}


# ---------------------------------------------------------------------------
# GET /api/projects/{id}/worktree — the thin route over the service
# ---------------------------------------------------------------------------


class TestWorktreeRoute:
    def test_returns_200_with_the_shape_off_git(self, client, registered: str) -> None:
        resp = client.get(f"/api/projects/{registered}/worktree")
        assert resp.status_code == 200
        assert resp.json() == {"dirty": False}

    def test_reports_dirty_true_for_an_uncommitted_non_alc_file(
        self, client, registered: str, project: Path
    ) -> None:
        _git_init(project)
        (project / "src.py").write_text("print('wip')\n")

        resp = client.get(f"/api/projects/{registered}/worktree")
        assert resp.status_code == 200
        assert resp.json() == {"dirty": True}

    def test_reports_dirty_false_on_a_clean_tree(
        self, client, registered: str, project: Path
    ) -> None:
        _git_init(project)

        resp = client.get(f"/api/projects/{registered}/worktree")
        assert resp.status_code == 200
        assert resp.json() == {"dirty": False}
