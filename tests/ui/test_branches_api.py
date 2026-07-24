# test_branches_api.py — GET /branches, POST /branches/land, POST /branches/discard.
# `client`/`registered`/`project` come from conftest.py (a non-git scaffolded
# project); git-backed tests here layer a real LOCAL repo on top, mirroring
# the house style (tests/test_land.py / tests/test_discard.py).
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _git_init(repo: Path) -> None:
    """Turn an already-scaffolded project directory into a git repo with one seed commit."""
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.email", "test@alc.local")
    _git(repo, "config", "user.name", "ALC Test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")


def _make_branch(repo: Path, branch: str, filename: str, content: str) -> None:
    _git(repo, "checkout", "-b", branch, "main")
    (repo / filename).write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", f"feat(auto): {branch}")
    _git(repo, "checkout", "main")


def _branch_exists(repo: Path, branch: str) -> bool:
    return _git(repo, "branch", "--list", branch).stdout.strip() != ""


@pytest.fixture
def git_project(make_project) -> Path:
    root = make_project("gitrepo")
    _git_init(root)
    return root


@pytest.fixture
def git_registered(client, git_project: Path) -> str:
    resp = client.post("/api/projects", json={"path": str(git_project)})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


class TestListBranches:
    def test_outside_git_repo_is_a_clear_unavailable_result(
        self, client, registered: str
    ) -> None:
        resp = client.get(f"/api/projects/{registered}/branches")
        assert resp.status_code == 200
        assert resp.json() == {"available": False, "branches": []}

    def test_lists_alc_branches_with_label_and_merged_flag(
        self, client, git_registered: str, git_project: Path
    ) -> None:
        _make_branch(git_project, "alc/tick-aaaaaaaa", "a.txt", "a\n")

        resp = client.get(f"/api/projects/{git_registered}/branches")
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is True
        [branch] = body["branches"]
        assert branch["name"] == "alc/tick-aaaaaaaa"
        assert branch["label"] == "tick"
        assert branch["merged"] is False


class TestLandBranches:
    def test_lands_every_unmerged_branch_when_omitted(
        self, client, git_registered: str, git_project: Path
    ) -> None:
        _make_branch(git_project, "alc/tick-aaa", "a.txt", "a\n")
        _make_branch(git_project, "alc/tick-bbb", "b.txt", "b\n")

        resp = client.post(f"/api/projects/{git_registered}/branches/land", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert sorted(body["merged"]) == ["alc/tick-aaa", "alc/tick-bbb"]
        assert body["conflicted"] == []
        assert not _branch_exists(git_project, "alc/tick-aaa")
        assert not _branch_exists(git_project, "alc/tick-bbb")

    def test_lands_only_the_named_branches(
        self, client, git_registered: str, git_project: Path
    ) -> None:
        _make_branch(git_project, "alc/tick-aaa", "a.txt", "a\n")
        _make_branch(git_project, "alc/tick-bbb", "b.txt", "b\n")

        resp = client.post(
            f"/api/projects/{git_registered}/branches/land",
            json={"branches": ["alc/tick-aaa"]},
        )
        assert resp.status_code == 200
        assert resp.json()["merged"] == ["alc/tick-aaa"]
        assert not _branch_exists(git_project, "alc/tick-aaa")
        assert _branch_exists(git_project, "alc/tick-bbb")

    def test_conflicted_branch_is_left_intact_and_reported(
        self, client, git_registered: str, git_project: Path
    ) -> None:
        (git_project / "seed.txt").write_text("line-a\n")
        _git(git_project, "add", "-A")
        _git(git_project, "commit", "-m", "seed")
        _make_branch(git_project, "alc/tick-aaa", "seed.txt", "from-a\n")
        _make_branch(git_project, "alc/tick-bbb", "seed.txt", "from-b\n")

        resp = client.post(f"/api/projects/{git_registered}/branches/land", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert body["merged"] == ["alc/tick-aaa"]
        assert body["conflicted"] == ["alc/tick-bbb"]
        assert _branch_exists(git_project, "alc/tick-bbb")

    def test_outside_git_repo_is_a_clear_error_not_500(
        self, client, registered: str
    ) -> None:
        resp = client.post(f"/api/projects/{registered}/branches/land", json={})
        assert resp.status_code == 409
        assert "git repository" in resp.json()["detail"]


class TestDiscardBranches:
    def test_deletes_the_named_branches(
        self, client, git_registered: str, git_project: Path
    ) -> None:
        _make_branch(git_project, "alc/tick-aaa", "a.txt", "a\n")
        _make_branch(git_project, "alc/tick-bbb", "b.txt", "b\n")

        resp = client.post(
            f"/api/projects/{git_registered}/branches/discard",
            json={"branches": ["alc/tick-aaa"]},
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] == ["alc/tick-aaa"]
        assert not _branch_exists(git_project, "alc/tick-aaa")
        assert _branch_exists(git_project, "alc/tick-bbb")

    def test_non_alc_branch_is_silently_skipped_by_delete_branches(
        self, client, git_registered: str, git_project: Path
    ) -> None:
        _git(git_project, "branch", "feature/not-alc")

        resp = client.post(
            f"/api/projects/{git_registered}/branches/discard",
            json={"branches": ["feature/not-alc"]},
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] == []
        assert _branch_exists(git_project, "feature/not-alc")

    def test_worktrees_flag_prunes_stale_entries(
        self, client, git_registered: str, git_project: Path, tmp_path: Path
    ) -> None:
        wt_path = tmp_path / "wt1"
        _git(git_project, "worktree", "add", str(wt_path), "-b", "alc/wt-aaaaaaaa")
        shutil.rmtree(wt_path)

        resp = client.post(
            f"/api/projects/{git_registered}/branches/discard",
            json={"branches": [], "worktrees": True},
        )
        assert resp.status_code == 200
        assert resp.json()["pruned_worktrees"] == 1

    def test_bundles_older_than_deletes_only_the_old_ones(
        self, client, git_registered: str, git_project: Path
    ) -> None:
        bundles_dir = git_project / ".alc" / "bundles"
        bundles_dir.mkdir(parents=True, exist_ok=True)
        old_bundle = bundles_dir / "old.jsonl"
        old_bundle.write_text("{}\n")
        new_bundle = bundles_dir / "new.jsonl"
        new_bundle.write_text("{}\n")
        old_time = time.time() - 40 * 86400
        os.utime(old_bundle, (old_time, old_time))

        resp = client.post(
            f"/api/projects/{git_registered}/branches/discard",
            json={"branches": [], "bundles": {"older_than_days": 30}},
        )
        assert resp.status_code == 200
        assert resp.json()["deleted_bundles"] == ["old.jsonl"]
        assert not old_bundle.exists()
        assert new_bundle.exists()

    def test_outside_git_repo_is_a_clear_error_not_500(
        self, client, registered: str
    ) -> None:
        resp = client.post(
            f"/api/projects/{registered}/branches/discard",
            json={"branches": ["alc/tick-aaa"]},
        )
        assert resp.status_code == 409
        assert "git repository" in resp.json()["detail"]
