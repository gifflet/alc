# test_compare_adopt.py — Hermetic tests for `alc compare` and `alc adopt`.
# Uses a real LOCAL git repository created in tmp_path; no model is called.
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from alc.cli import cmd_adopt, cmd_compare
from alc.models import AttemptRecord, RunReport, Scorecard, UnitResult
from alc.variants import write_variant

# ---------------------------------------------------------------------------
# Inline git helpers — mirror the house style (test_land.py / test_discard.py).
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _make_git_repo(base: Path) -> Path:
    repo = base / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.email", "test@alc.local")
    _git(repo, "config", "user.name", "ALC Test")
    (repo / "seed.txt").write_text("line-a\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    return repo


def _make_branch(repo: Path, branch: str, filename: str, content: str) -> None:
    _git(repo, "checkout", "-b", branch, "main")
    (repo / filename).write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", f"feat(auto): {branch}")
    _git(repo, "checkout", "main")


def _branch_exists(repo: Path, branch: str) -> bool:
    return _git(repo, "branch", "--list", branch).stdout.strip() != ""


_MANIFEST = """\
version: 1
default_engine: mock
compute_tiers:
  standard:
    mock: mock-small
engines:
  mock:
    type: mock
"""


def _make_alc_dir(repo: Path) -> Path:
    alc = repo / ".alc"
    alc.mkdir()
    (alc / "manifest.yaml").write_text(_MANIFEST)
    return alc


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


def _ns_compare(**overrides) -> argparse.Namespace:
    defaults = {"refs": [], "json": False, "diff": False}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _ns_adopt(**overrides) -> argparse.Namespace:
    defaults = {"branch": "", "yes": False, "json": False}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# alc compare
# ---------------------------------------------------------------------------


class TestCompare:
    def test_prints_a_block_per_found_variant(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        alc = _make_alc_dir(repo)
        _seed_variant(alc / "variants", "alc/variant-1-aaaaaaaa")
        _seed_variant(
            alc / "variants",
            "alc/variant-2-bbbbbbbb",
            success=False,
            failed_checks=["smoke"],
        )
        monkeypatch.chdir(repo)

        rc = cmd_compare(
            _ns_compare(refs=["alc/variant-1-aaaaaaaa", "alc/variant-2-bbbbbbbb"])
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "alc/variant-1-aaaaaaaa" in out
        assert "alc/variant-2-bbbbbbbb" in out
        assert "all passed" in out
        assert "failed: smoke" in out

    def test_accepts_a_bare_stem_as_well_as_the_full_branch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        alc = _make_alc_dir(repo)
        _seed_variant(alc / "variants", "alc/variant-1-aaaaaaaa")
        monkeypatch.chdir(repo)

        assert cmd_compare(_ns_compare(refs=["variant-1-aaaaaaaa"])) == 0
        assert "alc/variant-1-aaaaaaaa" in capsys.readouterr().out

    def test_json_output_carries_the_same_columns_as_explore(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        alc = _make_alc_dir(repo)
        _seed_variant(alc / "variants", "alc/variant-1-aaaaaaaa")
        monkeypatch.chdir(repo)

        assert cmd_compare(_ns_compare(refs=["alc/variant-1-aaaaaaaa"], json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert len(data) == 1
        row = data[0]
        assert row["branch"] == "alc/variant-1-aaaaaaaa"
        assert row["engine"] == "mock"
        assert row["tier"] == "standard"
        assert row["scorecard"]["span"] == 1
        assert row["checks"] == "all passed"

    def test_missing_ref_is_reported_on_stderr_and_exits_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _make_alc_dir(repo)
        monkeypatch.chdir(repo)

        rc = cmd_compare(_ns_compare(refs=["alc/variant-9-ffffffff"]))
        assert rc == 1
        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert "alc/variant-9-ffffffff" in err

    def test_found_refs_still_print_when_another_ref_is_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        alc = _make_alc_dir(repo)
        _seed_variant(alc / "variants", "alc/variant-1-aaaaaaaa")
        monkeypatch.chdir(repo)

        rc = cmd_compare(
            _ns_compare(refs=["alc/variant-1-aaaaaaaa", "alc/variant-9-ffffffff"])
        )
        assert rc == 1
        out, err = capsys.readouterr()
        assert "alc/variant-1-aaaaaaaa" in out
        assert "alc/variant-9-ffffffff" in err


class TestCompareDiff:
    def test_diff_flag_prints_each_variant_s_diff(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        # Create the real branch BEFORE the .alc dir exists, so the branch's
        # commit never sweeps in the (untracked) operator layer.
        _make_branch(repo, "alc/variant-1-aaaaaaaa", "win.txt", "winner\n")
        alc = _make_alc_dir(repo)
        _seed_variant(alc / "variants", "alc/variant-1-aaaaaaaa")
        monkeypatch.chdir(repo)

        rc = cmd_compare(_ns_compare(refs=["alc/variant-1-aaaaaaaa"], diff=True))
        assert rc == 0
        out = capsys.readouterr().out
        assert "Diff:" in out
        assert "+winner" in out

    def test_diff_of_a_deleted_branch_degrades_per_variant_not_fatal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        # The archive outlives its branch (adopt deletes losers). A missing
        # branch is per-variant degradation, not a command failure.
        repo = _make_git_repo(tmp_path)
        alc = _make_alc_dir(repo)
        _seed_variant(alc / "variants", "alc/variant-1-aaaaaaaa")  # branch never created
        monkeypatch.chdir(repo)

        rc = cmd_compare(_ns_compare(refs=["alc/variant-1-aaaaaaaa"], diff=True))
        assert rc == 0
        out = capsys.readouterr().out
        assert "(no diff available" in out

    def test_json_with_diff_carries_diff_fields(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/variant-1-aaaaaaaa", "win.txt", "winner\n")
        alc = _make_alc_dir(repo)
        _seed_variant(alc / "variants", "alc/variant-1-aaaaaaaa")
        monkeypatch.chdir(repo)

        rc = cmd_compare(
            _ns_compare(refs=["alc/variant-1-aaaaaaaa"], json=True, diff=True)
        )
        assert rc == 0
        row = json.loads(capsys.readouterr().out)[0]
        assert "+winner" in row["diff"]
        assert row["diff_truncated"] is False

    def test_plain_json_carries_no_diff_fields(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/variant-1-aaaaaaaa", "win.txt", "winner\n")
        alc = _make_alc_dir(repo)
        _seed_variant(alc / "variants", "alc/variant-1-aaaaaaaa")
        monkeypatch.chdir(repo)

        rc = cmd_compare(_ns_compare(refs=["alc/variant-1-aaaaaaaa"], json=True))
        assert rc == 0
        row = json.loads(capsys.readouterr().out)[0]
        assert "diff" not in row
        assert "diff_truncated" not in row

    def test_diff_outside_git_errors_on_stderr_but_still_prints_the_table(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        # A bare .alc archive with no git repo around it: the diffs are
        # unavailable, but the summary table the operator asked for still prints.
        project = tmp_path / "not-a-repo"
        project.mkdir()
        alc = project / ".alc"
        alc.mkdir()
        (alc / "manifest.yaml").write_text(_MANIFEST)
        _seed_variant(alc / "variants", "alc/variant-1-aaaaaaaa")
        monkeypatch.chdir(project)

        rc = cmd_compare(_ns_compare(refs=["alc/variant-1-aaaaaaaa"], diff=True))
        assert rc == 1
        out, err = capsys.readouterr()
        assert "[ERROR]" in err
        assert "not inside a git repository" in err
        assert "alc/variant-1-aaaaaaaa" in out  # the table still printed


# ---------------------------------------------------------------------------
# alc adopt
# ---------------------------------------------------------------------------


class TestAdopt:
    def test_merges_winner_and_discards_variant_siblings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/variant-1-aaaaaaaa", "a.txt", "winner\n")
        _make_branch(repo, "alc/variant-2-bbbbbbbb", "b.txt", "loser\n")
        # An unrelated unmerged branch must be left ALONE — adopt only
        # discards VARIANT siblings, never every unmerged alc/* branch.
        _make_branch(repo, "alc/tick-cccccccc", "c.txt", "unrelated\n")
        monkeypatch.chdir(repo)

        rc = cmd_adopt(_ns_adopt(branch="alc/variant-1-aaaaaaaa", yes=True))
        assert rc == 0
        assert (repo / "a.txt").read_text() == "winner\n"
        assert not _branch_exists(repo, "alc/variant-1-aaaaaaaa")
        assert not _branch_exists(repo, "alc/variant-2-bbbbbbbb")
        assert _branch_exists(repo, "alc/tick-cccccccc")
        out = capsys.readouterr().out
        assert "merged 1" in out
        assert "Discarded 1 losing variant" in out

    def test_json_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/variant-1-aaaaaaaa", "a.txt", "winner\n")
        _make_branch(repo, "alc/variant-2-bbbbbbbb", "b.txt", "loser\n")
        monkeypatch.chdir(repo)

        rc = cmd_adopt(_ns_adopt(branch="alc/variant-1-aaaaaaaa", yes=True, json=True))
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["merged"] == ["alc/variant-1-aaaaaaaa"]
        assert data["discarded"] == ["alc/variant-2-bbbbbbbb"]

    def test_no_sibling_variants_discards_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/variant-1-aaaaaaaa", "a.txt", "winner\n")
        monkeypatch.chdir(repo)

        assert cmd_adopt(_ns_adopt(branch="alc/variant-1-aaaaaaaa", yes=True)) == 0
        assert "Discarded 0 losing variant(s)." in capsys.readouterr().out

    def test_rejects_a_non_alc_branch_before_touching_anything(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _git(repo, "branch", "feature/not-alc")
        monkeypatch.chdir(repo)

        rc = cmd_adopt(_ns_adopt(branch="feature/not-alc", yes=True))
        assert rc == 1
        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert "not an alc/ branch" in err
        assert _branch_exists(repo, "feature/not-alc")

    def test_outside_git_repo_is_a_clear_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        non_repo = tmp_path / "not-a-repo"
        non_repo.mkdir()
        monkeypatch.chdir(non_repo)

        rc = cmd_adopt(_ns_adopt(branch="alc/variant-1-aaaaaaaa", yes=True))
        assert rc == 1
        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert "not inside a git repository" in err

    def test_non_tty_without_yes_refuses_and_touches_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/variant-1-aaaaaaaa", "a.txt", "winner\n")
        _make_branch(repo, "alc/variant-2-bbbbbbbb", "b.txt", "loser\n")
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        rc = cmd_adopt(_ns_adopt(branch="alc/variant-1-aaaaaaaa"))
        assert rc == 1
        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert "confirmation" in err
        assert _branch_exists(repo, "alc/variant-1-aaaaaaaa")
        assert _branch_exists(repo, "alc/variant-2-bbbbbbbb")
        assert not (repo / "a.txt").exists()  # nothing merged either

    def test_yes_flag_skips_the_prompt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/variant-1-aaaaaaaa", "a.txt", "winner\n")
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        assert cmd_adopt(_ns_adopt(branch="alc/variant-1-aaaaaaaa", yes=True)) == 0
        assert not _branch_exists(repo, "alc/variant-1-aaaaaaaa")

    def test_tty_prompt_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/variant-1-aaaaaaaa", "a.txt", "winner\n")
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda prompt="": "y")

        assert cmd_adopt(_ns_adopt(branch="alc/variant-1-aaaaaaaa")) == 0
        assert not _branch_exists(repo, "alc/variant-1-aaaaaaaa")

    def test_tty_prompt_declined_refuses(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/variant-1-aaaaaaaa", "a.txt", "winner\n")
        monkeypatch.chdir(repo)
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda prompt="": "n")

        assert cmd_adopt(_ns_adopt(branch="alc/variant-1-aaaaaaaa")) == 1
        assert _branch_exists(repo, "alc/variant-1-aaaaaaaa")

    def test_conflicted_merge_leaves_the_branch_and_exits_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        # Both branches rewrite seed.txt's line 1 differently -> conflict.
        _make_branch(repo, "alc/variant-1-aaaaaaaa", "seed.txt", "from-variant\n")
        (repo / "seed.txt").write_text("from-main\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "diverge main")
        monkeypatch.chdir(repo)

        rc = cmd_adopt(_ns_adopt(branch="alc/variant-1-aaaaaaaa", yes=True))
        assert rc == 1
        assert _branch_exists(repo, "alc/variant-1-aaaaaaaa")
