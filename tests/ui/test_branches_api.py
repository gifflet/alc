# test_branches_api.py — GET /branches, POST /branches/land, POST /branches/discard.
# `client`/`registered`/`project` come from conftest.py (a non-git scaffolded
# project); git-backed tests here layer a real LOCAL repo on top, mirroring
# the house style (tests/test_land.py / tests/test_discard.py). The land-with-
# delivery tests (push/PR) reuse tests/test_delivery.py's pattern: a local bare
# repo standing in for the remote, and a FAKE `gh` binary on PATH — never a
# real push and never the real `gh`.
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
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


def _make_bare_remote(base: Path) -> Path:
    """Initialize a local BARE repo standing in for a remote. Never a real push."""
    remote = base / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)], check=True, capture_output=True
    )
    return remote


def _install_fake_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put a fake `gh` binary first on PATH; return its backing state file.

    `gh pr create ...` records its --base/--head/--title/--body into the state
    file as JSON and prints a fake PR URL. The real `gh` is never invoked by
    any test in this file. Mirrors tests/test_delivery.py's helper.
    """
    state = tmp_path / "gh.state.json"
    bin_dir = tmp_path / "fakebin-gh"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "gh"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys, pathlib\n"
        f"STATE = pathlib.Path({str(state)!r})\n"
        "args = sys.argv[1:]\n"
        "def opt(name):\n"
        "    return args[args.index(name) + 1] if name in args else None\n"
        "STATE.write_text(json.dumps({\n"
        "    'base': opt('--base'), 'head': opt('--head'),\n"
        "    'title': opt('--title'), 'body': opt('--body'),\n"
        "}))\n"
        "print('https://example.invalid/pr/1')\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    return state


def _path_with_only_git(tmp_path: Path) -> str:
    """Return a PATH entry that resolves `git` but nothing else (notably not `gh`)."""
    bin_dir = tmp_path / "gitonly-bin"
    bin_dir.mkdir(exist_ok=True)
    git_path = shutil.which("git")
    assert git_path is not None
    link = bin_dir / "git"
    if not link.exists():
        link.symlink_to(git_path)
    return str(bin_dir)


def _add_delivery_to_manifest(
    root: Path, mode: str, remote: str = "origin", base: str = "main"
) -> None:
    """Append a `delivery:` block to an already-scaffolded project's manifest.yaml."""
    manifest_path = root / ".alc" / "manifest.yaml"
    text = manifest_path.read_text()
    text += f"\ndelivery:\n  mode: {mode}\n  remote: {remote}\n  base: {base}\n"
    manifest_path.write_text(text)


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
        # `mode` omitted, no manifest `delivery` -> local, byte-identical: no
        # delivery is attempted at all, so there is no `warning` key either.
        assert "warning" not in body

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


class TestLandBranchesDelivery:
    """`mode: push|pr`: the remote last mile wrapped
    over `alc.delivery`, never a real push and never the real `gh`."""

    def test_mode_push_pushes_the_landed_branch(
        self, client, git_registered: str, git_project: Path, tmp_path: Path
    ) -> None:
        remote = _make_bare_remote(tmp_path)
        _git(git_project, "remote", "add", "origin", str(remote))
        _make_branch(git_project, "alc/tick-aaa", "a.txt", "a\n")

        resp = client.post(
            f"/api/projects/{git_registered}/branches/land",
            json={"mode": "push"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["merged"] == ["alc/tick-aaa"]
        assert body["warning"] is None
        local_sha = _git(git_project, "rev-parse", "main").stdout.strip()
        remote_sha = subprocess.run(
            ["git", "--git-dir", str(remote), "rev-parse", "main"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert remote_sha == local_sha

    def test_mode_push_failure_is_a_warning_not_a_500(
        self, client, git_registered: str, git_project: Path
    ) -> None:
        # No remote configured -> the push step fails; the local land already succeeded.
        _make_branch(git_project, "alc/tick-aaa", "a.txt", "a\n")

        resp = client.post(
            f"/api/projects/{git_registered}/branches/land",
            json={"mode": "push"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["merged"] == ["alc/tick-aaa"]  # the local merge still succeeded
        assert not _branch_exists(git_project, "alc/tick-aaa")  # ... and is really landed
        assert body["warning"] is not None
        assert "failed" in body["warning"]

    def test_mode_pr_opens_a_pr_via_the_fake_gh(
        self,
        client,
        git_registered: str,
        git_project: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        remote = _make_bare_remote(tmp_path)
        _git(git_project, "remote", "add", "origin", str(remote))
        state = _install_fake_gh(tmp_path, monkeypatch)
        _make_branch(git_project, "alc/tick-aaa", "a.txt", "a\n")

        resp = client.post(
            f"/api/projects/{git_registered}/branches/land",
            json={"mode": "pr"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["merged"] == ["alc/tick-aaa"]
        assert body["warning"] is None
        data = json.loads(state.read_text())
        assert data["base"] == "main"
        assert data["head"] == "main"
        assert "alc/tick-aaa" in data["body"]

    def test_mode_pr_with_gh_missing_is_a_warning_not_a_500(
        self,
        client,
        git_registered: str,
        git_project: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        remote = _make_bare_remote(tmp_path)
        _git(git_project, "remote", "add", "origin", str(remote))
        _make_branch(git_project, "alc/tick-aaa", "a.txt", "a\n")
        monkeypatch.setenv("PATH", _path_with_only_git(tmp_path))  # git yes, gh no

        resp = client.post(
            f"/api/projects/{git_registered}/branches/land",
            json={"mode": "pr"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["merged"] == ["alc/tick-aaa"]
        assert body["warning"] is not None
        assert "gh not installed" in body["warning"]

    def test_manifest_delivery_mode_is_used_when_the_body_omits_mode(
        self, client, git_registered: str, git_project: Path, tmp_path: Path
    ) -> None:
        remote = _make_bare_remote(tmp_path)
        _git(git_project, "remote", "add", "origin", str(remote))
        _add_delivery_to_manifest(git_project, mode="push")
        _make_branch(git_project, "alc/tick-aaa", "a.txt", "a\n")

        resp = client.post(f"/api/projects/{git_registered}/branches/land", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert body["warning"] is None
        local_sha = _git(git_project, "rev-parse", "main").stdout.strip()
        remote_sha = subprocess.run(
            ["git", "--git-dir", str(remote), "rev-parse", "main"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert remote_sha == local_sha

    def test_body_mode_overrides_the_manifest_delivery_mode(
        self, client, git_registered: str, git_project: Path, tmp_path: Path
    ) -> None:
        # Manifest defaults to push; the request explicitly asks for local -> no delivery.
        _add_delivery_to_manifest(git_project, mode="push")
        _make_branch(git_project, "alc/tick-aaa", "a.txt", "a\n")

        resp = client.post(
            f"/api/projects/{git_registered}/branches/land",
            json={"mode": "local"},
        )
        assert resp.status_code == 200
        assert "warning" not in resp.json()


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

    def test_discard_removes_an_orphaned_worktree_holding_the_branch(
        self, client, git_registered: str, git_project: Path, tmp_path: Path
    ) -> None:
        """The UI discard (POST /branches/discard) shares delete_branches with the
        CLI, so it too force-removes an isolated worktree left by an INTERRUPTED run
        (branch checked out + uncommitted changes) before deleting the branch —
        instead of returning deleted=[] and leaving the mess."""
        wt = tmp_path / "alc-wt-orphan"
        _git(git_project, "worktree", "add", "-b", "alc/run-orphan0", str(wt), "main")
        (wt / "dirty.txt").write_text("uncommitted work from an interrupted run\n")
        assert _git(git_project, "branch", "-D", "alc/run-orphan0").returncode != 0

        resp = client.post(
            f"/api/projects/{git_registered}/branches/discard",
            json={"branches": ["alc/run-orphan0"]},
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] == ["alc/run-orphan0"]
        assert not _branch_exists(git_project, "alc/run-orphan0")
        assert not wt.exists()

    def test_discard_removes_the_branch_run_report(
        self, client, git_registered: str, git_project: Path
    ) -> None:
        """The UI discard shares delete_branches + passes runs_dir, so discarding a
        branch also deletes the isolated run's archived report — it stops counting in
        audit / Mix Health, same as the CLI."""
        from alc.branches import run_report_filename

        _make_branch(git_project, "alc/run-abc12345", "x.txt", "x\n")
        runs = git_project / ".alc" / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        report = runs / run_report_filename("alc/run-abc12345")
        report.write_text("{}")

        resp = client.post(
            f"/api/projects/{git_registered}/branches/discard",
            json={"branches": ["alc/run-abc12345"]},
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] == ["alc/run-abc12345"]
        assert not report.exists()

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
