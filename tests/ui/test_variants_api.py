# test_variants_api.py — GET /variants (compare) and POST /variants/adopt.
# `client`/`registered`/`project` come from conftest.py; git-backed adopt
# tests layer a real LOCAL repo on top, mirroring tests/test_compare_adopt.py.
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from alc.models import AttemptRecord, RunReport, Scorecard, UnitResult
from alc.variants import write_variant


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _git_init(repo: Path) -> None:
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


def _seed_variant(
    variants_dir: Path,
    branch: str,
    *,
    success: bool = True,
    failed_checks: list[str] | None = None,
) -> None:
    """Archive one variant record, standing in for a prior `alc explore` run."""
    run_report = RunReport(
        blueprint="chore",
        engine="mock",
        success=success,
        attempts=[
            AttemptRecord(index=0, engine_ok=True, failed_checks=failed_checks or [])
        ],
        scorecard=Scorecard(span=1, passes=1, streak=1, touch=0),
        output_text="[mock] applied",
    )
    unit = UnitResult(
        kind="blueprint",
        name="chore",
        task="do it",
        success=success,
        branch=branch,
        run_report=run_report,
    )
    write_variant(variants_dir, branch, "mock", "standard", unit)


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


class TestListVariants:
    def test_no_variants_dir_is_an_empty_list(self, client, registered: str) -> None:
        resp = client.get(f"/api/projects/{registered}/variants")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_lists_archived_variants_as_comparable_rows(
        self, client, registered: str, project: Path
    ) -> None:
        variants_dir = project / ".alc" / "variants"
        _seed_variant(variants_dir, "alc/variant-1-aaaaaaaa")
        _seed_variant(
            variants_dir, "alc/variant-2-bbbbbbbb", success=False, failed_checks=["smoke"]
        )

        resp = client.get(f"/api/projects/{registered}/variants")
        assert resp.status_code == 200
        rows = resp.json()
        by_branch = {r["branch"]: r for r in rows}
        assert set(by_branch) == {"alc/variant-1-aaaaaaaa", "alc/variant-2-bbbbbbbb"}
        assert by_branch["alc/variant-1-aaaaaaaa"]["checks"] == "all passed"
        assert by_branch["alc/variant-2-bbbbbbbb"]["checks"] == "failed: smoke"
        assert by_branch["alc/variant-1-aaaaaaaa"]["engine"] == "mock"
        assert by_branch["alc/variant-1-aaaaaaaa"]["tier"] == "standard"


class TestAdoptVariant:
    def test_integrates_the_winner_and_discards_siblings(
        self, client, git_registered: str, git_project: Path
    ) -> None:
        _make_branch(git_project, "alc/variant-1-aaaaaaaa", "a.txt", "winner\n")
        _make_branch(git_project, "alc/variant-2-bbbbbbbb", "b.txt", "loser\n")
        # An unrelated unmerged branch must be left ALONE — adopt only
        # discards VARIANT siblings, never every unmerged alc/* branch.
        _make_branch(git_project, "alc/tick-cccccccc", "c.txt", "unrelated\n")

        resp = client.post(
            f"/api/projects/{git_registered}/variants/adopt",
            json={"branch": "alc/variant-1-aaaaaaaa"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["merged"] == ["alc/variant-1-aaaaaaaa"]
        assert body["discarded"] == ["alc/variant-2-bbbbbbbb"]
        assert (git_project / "a.txt").read_text() == "winner\n"
        assert not _branch_exists(git_project, "alc/variant-1-aaaaaaaa")
        assert not _branch_exists(git_project, "alc/variant-2-bbbbbbbb")
        assert _branch_exists(git_project, "alc/tick-cccccccc")

    def test_rejects_a_non_alc_branch(self, client, git_registered: str) -> None:
        resp = client.post(
            f"/api/projects/{git_registered}/variants/adopt",
            json={"branch": "not-alc"},
        )
        assert resp.status_code == 422

    def test_outside_git_repo_is_a_clear_error_not_500(
        self, client, registered: str
    ) -> None:
        resp = client.post(
            f"/api/projects/{registered}/variants/adopt",
            json={"branch": "alc/variant-1-aaaaaaaa"},
        )
        assert resp.status_code == 409
        assert "git repository" in resp.json()["detail"]
