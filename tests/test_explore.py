# test_explore.py — Hermetic tests for `alc explore`.
# Uses a real LOCAL git repository created in tmp_path + the Mock engine; no
# model is called.
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from alc.cli import cmd_explore

# ---------------------------------------------------------------------------
# Inline git helpers — mirror the house style (test_fanout.py / test_land.py).
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _init_git_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.email", "test@alc.local")
    _git(repo, "config", "user.name", "ALC Test")


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)


def _branches(repo: Path) -> list[str]:
    result = _git(repo, "branch", "--format=%(refname:short)")
    return [b.strip() for b in result.stdout.splitlines() if b.strip()]


_MANIFEST = """\
version: 1
default_engine: mock
compute_tiers:
  standard:
    mock: mock-small
  deep:
    mock: mock-large
engines:
  mock:
    type: mock
blueprints_dir: .alc/blueprints
flows_dir: .alc/flows
queue_dir: .alc/queue
"""

_MANIFEST_TWO_ENGINES_TWO_TIERS = """\
version: 1
default_engine: mock
compute_tiers:
  standard:
    mock: mock-small
    other: other-small
  deep:
    mock: mock-large
    other: other-large
engines:
  mock:
    type: mock
  other:
    type: mock
blueprints_dir: .alc/blueprints
flows_dir: .alc/flows
queue_dir: .alc/queue
"""

_CHORE = """\
---
name: chore
purpose: Apply a low-risk, well-scoped maintenance change.
compute_tier: standard
checks:
  - name: smoke
    command: ["true"]
---
# Workflow
1. Make the smallest change that satisfies the task; keep it single-purpose.
"""


def _make_repo(tmp_path: Path, manifest_text: str = _MANIFEST) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    alc = repo / ".alc"
    (alc / "blueprints").mkdir(parents=True)
    (alc / "flows").mkdir(parents=True)
    (alc / "manifest.yaml").write_text(manifest_text)
    (alc / "blueprints" / "chore.md").write_text(_CHORE)
    (repo / "seed.txt").write_text("seed\n")
    _commit_all(repo, "seed operator layer")
    return repo


def _ns(**overrides) -> argparse.Namespace:
    defaults = {
        "blueprint": "chore",
        "task": "do it",
        "variants": 1,
        "engine": None,
        "tier": None,
        "json": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.fixture
def write_engine(monkeypatch: pytest.MonkeyPatch):
    """Patch resolve_engine so every unit's Act WRITES a file — the worktree
    then has something to commit, so every variant produces a branch.
    """
    from alc.engine import Capabilities, EngineResult

    class _WriteEngine:
        def __init__(self, name: str = "mock") -> None:
            self.name = name

        def capabilities(self) -> Capabilities:
            return Capabilities()

        def health_check(self) -> bool:
            return True

        def run(self, request):
            (request.workdir / f"{self.name}.txt").write_text("done\n")
            return EngineResult(ok=True, output_text="[mock] applied")

    monkeypatch.setattr(
        "alc.runner.resolve_engine", lambda name, cfg: _WriteEngine(name)
    )


# ---------------------------------------------------------------------------
# --variants N alone — N copies of the same unit.
# ---------------------------------------------------------------------------


class TestExploreVariantsCount:
    def test_variants_n_alone_repeats_the_default_unit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write_engine
    ) -> None:
        repo = _make_repo(tmp_path)
        monkeypatch.chdir(repo)

        assert cmd_explore(_ns(variants=3)) == 0
        variant_branches = [b for b in _branches(repo) if b.startswith("alc/variant-")]
        assert len(variant_branches) == 3
        for n in (1, 2, 3):
            assert any(b.startswith(f"alc/variant-{n}-") for b in variant_branches)

    def test_never_auto_merges(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write_engine
    ) -> None:
        repo = _make_repo(tmp_path)
        monkeypatch.chdir(repo)
        head_before = _git(repo, "rev-parse", "HEAD").stdout.strip()

        assert cmd_explore(_ns(variants=2)) == 0

        head_after = _git(repo, "rev-parse", "HEAD").stdout.strip()
        assert head_before == head_after  # nothing landed on the current branch
        # The variant branches are still there, unmerged, for the operator to pick.
        assert len([b for b in _branches(repo) if b.startswith("alc/variant-")]) == 2

    def test_variants_must_be_positive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_repo(tmp_path)
        monkeypatch.chdir(repo)

        assert cmd_explore(_ns(variants=0)) == 1
        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert "--variants" in err


# ---------------------------------------------------------------------------
# --engine / --tier cartesian product.
# ---------------------------------------------------------------------------


class TestExploreCartesianProduct:
    def test_engine_and_tier_cross_product(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, write_engine
    ) -> None:
        repo = _make_repo(tmp_path, manifest_text=_MANIFEST_TWO_ENGINES_TWO_TIERS)
        monkeypatch.chdir(repo)

        rc = cmd_explore(
            _ns(engine=["mock", "other"], tier=["standard", "deep"], json=True)
        )
        assert rc == 0
        rows = json.loads(capsys.readouterr().out)
        assert len(rows) == 4  # 2 engines x 2 tiers x 1 (default --variants)
        assert {r["engine"] for r in rows} == {"mock", "other"}
        assert {r["tier"] for r in rows} == {"standard", "deep"}
        variant_branches = [b for b in _branches(repo) if b.startswith("alc/variant-")]
        assert len(variant_branches) == 4

    def test_unknown_tier_is_rejected_before_running_anything(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_repo(tmp_path)
        monkeypatch.chdir(repo)

        assert cmd_explore(_ns(tier=["nonexistent"])) == 1
        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert "nonexistent" in err
        assert not [b for b in _branches(repo) if b.startswith("alc/variant-")]


# ---------------------------------------------------------------------------
# Row shape and archiving (feeds `alc compare`).
# ---------------------------------------------------------------------------


class TestExploreRowsAndArchive:
    def test_json_rows_carry_branch_checks_scorecard_usage_diffstat(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, write_engine
    ) -> None:
        repo = _make_repo(tmp_path)
        monkeypatch.chdir(repo)

        assert cmd_explore(_ns(variants=1, json=True)) == 0
        rows = json.loads(capsys.readouterr().out)
        assert len(rows) == 1
        row = rows[0]
        for key in ("branch", "engine", "tier", "success", "checks", "scorecard", "usage", "diffstat"):
            assert key in row
        assert row["branch"].startswith("alc/variant-1-")
        assert row["success"] is True
        assert row["checks"] == "all passed"
        assert row["scorecard"]["passes"] == 1

    def test_human_output_prints_one_block_per_variant(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, write_engine
    ) -> None:
        repo = _make_repo(tmp_path)
        monkeypatch.chdir(repo)

        assert cmd_explore(_ns(variants=2)) == 0
        out = capsys.readouterr().out
        assert "Variant 1" in out
        assert "Variant 2" in out
        assert "Status:    SUCCESS" in out

    def test_archives_each_committed_variant_by_branch_stem(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write_engine
    ) -> None:
        repo = _make_repo(tmp_path)
        monkeypatch.chdir(repo)

        assert cmd_explore(_ns(variants=2)) == 0
        variant_branches = sorted(
            b for b in _branches(repo) if b.startswith("alc/variant-")
        )
        assert len(variant_branches) == 2
        variants_dir = repo / ".alc" / "variants"
        for branch in variant_branches:
            stem = branch.removeprefix("alc/")
            archive = variants_dir / f"{stem}.json"
            assert archive.is_file(), f"no archive for {branch}"
            record = json.loads(archive.read_text())
            assert record["branch"] == branch
            assert record["unit"]["run_report"]["scorecard"]["passes"] == 1


# ---------------------------------------------------------------------------
# Per-unit failure isolation and non-git errors.
# ---------------------------------------------------------------------------


class TestExploreFailureHandling:
    def test_unknown_blueprint_fails_the_variant_without_a_traceback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_repo(tmp_path)
        monkeypatch.chdir(repo)

        rc = cmd_explore(_ns(blueprint="does-not-exist"))
        assert rc == 1
        out = capsys.readouterr().out
        assert "FAILED" in out
        # A failed (never-committed) variant has no branch to archive.
        assert not [b for b in _branches(repo) if b.startswith("alc/variant-")]

    def test_outside_git_repo_is_a_clear_error_not_a_traceback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        non_repo = tmp_path / "not-a-repo"
        non_repo.mkdir()
        alc = non_repo / ".alc"
        (alc / "blueprints").mkdir(parents=True)
        (alc / "manifest.yaml").write_text(_MANIFEST)
        (alc / "blueprints" / "chore.md").write_text(_CHORE)
        monkeypatch.chdir(non_repo)

        rc = cmd_explore(_ns())
        assert rc == 1
        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert "git repository" in err
