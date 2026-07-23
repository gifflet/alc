# test_delivery.py — Hermetic tests for T8: `DeliverySpec` + `alc land --push|--pr`.
#
# Two layers:
#   (1) alc.delivery — pure/git-level helpers, exercised against REAL local git
#       repos (a working repo + a bare "remote") and a FAKE `gh` binary put
#       first on PATH (same pattern as tests/test_schedule.py's fake `crontab`).
#   (2) cmd_land — the CLI wiring: --push/--pr, and the manifest `delivery`
#       default they override. No real push ever leaves this machine (the
#       "remote" is a local bare repo) and the real `gh` is never invoked.
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from alc.cli import cmd_land
from alc.delivery import (
    build_pr_body,
    changed_files,
    current_branch,
    has_gh,
    open_pr,
    push_branch,
)
from alc.merge import MergeReport
from alc.models import DeliverySpec, Manifest

# ---------------------------------------------------------------------------
# Inline git helpers — mirror the house style (test_land.py / test_merge.py).
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _make_git_repo(base: Path) -> Path:
    """Initialize a git repo with one seed commit on main and return its path."""
    repo = base / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.email", "test@alc.local")
    _git(repo, "config", "user.name", "ALC Test")
    (repo / "seed.txt").write_text("line-a\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    return repo


def _make_bare_remote(base: Path) -> Path:
    """Initialize a local BARE repo standing in for a remote. Never a real push."""
    remote = base / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)], check=True, capture_output=True
    )
    return remote


def _make_branch(repo: Path, branch: str, filename: str, content: str, subject: str) -> None:
    _git(repo, "checkout", "-b", branch, "main")
    (repo / filename).write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", subject)
    _git(repo, "checkout", "main")


def _write_delivery_manifest(
    repo: Path, mode: str | None = None, remote: str = "origin", base: str = "main"
) -> None:
    """Write a minimal `.alc/manifest.yaml` under *repo*, optionally with `delivery:`."""
    alc = repo / ".alc"
    alc.mkdir(exist_ok=True)
    delivery_block = ""
    if mode is not None:
        delivery_block = f"delivery:\n  mode: {mode}\n  remote: {remote}\n  base: {base}\n"
    (alc / "manifest.yaml").write_text(
        "version: 1\n"
        "default_engine: mock\n"
        "compute_tiers:\n  standard:\n    mock: mock-small\n"
        "engines:\n  mock:\n    type: mock\n"
        f"{delivery_block}"
    )


def _install_fake_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put a fake `gh` binary first on PATH; return its backing state file.

    `gh pr create ...` records its --base/--head/--title/--body into the state
    file as JSON and prints a fake PR URL. Set FAKE_GH_FAIL=1 (env) to make it
    fail instead. The real `gh` is never invoked by any test in this file.
    """
    state = tmp_path / "gh.state.json"
    bin_dir = tmp_path / "fakebin-gh"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "gh"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys, pathlib\n"
        f"STATE = pathlib.Path({str(state)!r})\n"
        "if os.environ.get('FAKE_GH_FAIL'):\n"
        "    sys.stderr.write('fake gh failure\\n')\n"
        "    sys.exit(1)\n"
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


# ---------------------------------------------------------------------------
# DeliverySpec — defaults keep `alc land` byte-identical when absent
# ---------------------------------------------------------------------------


class TestDeliverySpecDefaults:
    def test_defaults_to_local_origin_main(self) -> None:
        spec = DeliverySpec()
        assert spec.mode == "local"
        assert spec.remote == "origin"
        assert spec.base == "main"

    def test_manifest_delivery_defaults_to_none(self) -> None:
        manifest = Manifest(
            version=1,
            default_engine="mock",
            compute_tiers={"standard": {"mock": "mock-small"}},
            engines={"mock": {"type": "mock"}},
        )
        assert manifest.delivery is None


# ---------------------------------------------------------------------------
# alc.delivery — has_gh / current_branch
# ---------------------------------------------------------------------------


class TestHasGh:
    def test_false_when_gh_not_on_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        empty = tmp_path / "empty-bin"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        assert has_gh() is False

    def test_true_when_a_fake_gh_is_on_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_gh(tmp_path, monkeypatch)
        assert has_gh() is True


class TestCurrentBranch:
    def test_returns_the_checked_out_branch(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        assert current_branch(repo) == "main"

    def test_none_outside_a_git_repo(self, tmp_path: Path) -> None:
        non_repo = tmp_path / "not-a-repo"
        non_repo.mkdir()
        assert current_branch(non_repo) is None

    def test_none_when_git_is_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _make_git_repo(tmp_path)
        empty = tmp_path / "empty-bin"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        assert current_branch(repo) is None


# ---------------------------------------------------------------------------
# alc.delivery — push_branch (against a local bare "remote", never a real push)
# ---------------------------------------------------------------------------


class TestPushBranch:
    def test_pushes_successfully_to_a_configured_remote(self, tmp_path: Path) -> None:
        remote = _make_bare_remote(tmp_path)
        repo = _make_git_repo(tmp_path)
        _git(repo, "remote", "add", "origin", str(remote))

        ok, message = push_branch(repo, "origin", "main")

        assert ok is True
        assert "pushed main to origin" in message
        local_sha = _git(repo, "rev-parse", "main").stdout.strip()
        remote_sha = subprocess.run(
            ["git", "--git-dir", str(remote), "rev-parse", "main"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert remote_sha == local_sha

    def test_fails_gracefully_with_no_remote_configured(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        ok, message = push_branch(repo, "origin", "main")
        assert ok is False
        assert "failed" in message

    def test_fails_gracefully_when_git_is_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _make_git_repo(tmp_path)
        empty = tmp_path / "empty-bin"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        ok, message = push_branch(repo, "origin", "main")
        assert ok is False
        assert "git not found" in message


# ---------------------------------------------------------------------------
# alc.delivery — changed_files
# ---------------------------------------------------------------------------


class TestChangedFiles:
    def test_returns_paths_that_differ_between_base_and_head(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "feature", "new.txt", "hi\n", "add new.txt")

        assert changed_files(repo, "main", "feature") == ["new.txt"]

    def test_empty_on_an_unknown_ref(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path)
        assert changed_files(repo, "main", "does-not-exist") == []

    def test_empty_when_git_is_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _make_git_repo(tmp_path)
        empty = tmp_path / "empty-bin"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        assert changed_files(repo, "main", "main") == []


# ---------------------------------------------------------------------------
# alc.delivery — build_pr_body (pure)
# ---------------------------------------------------------------------------


class TestBuildPrBody:
    def test_includes_checks_scorecard_and_changed_files(self) -> None:
        report = MergeReport(merged=["alc/tick-aaa"], conflicted=["alc/tick-bbb"])
        body = build_pr_body(report, ["src/a.py", "src/b.py"])

        assert "## Checks" in body
        assert "alc/tick-aaa" in body
        assert "alc/tick-bbb" in body
        assert "## Scorecard" in body
        assert "Merged: 1" in body
        assert "Left: 1" in body
        assert "## Changed files" in body
        assert "src/a.py" in body
        assert "src/b.py" in body

    def test_handles_no_merges_and_no_files(self) -> None:
        report = MergeReport()
        body = build_pr_body(report, [])

        assert "No branches merged cleanly." in body
        assert "(none detected)" in body
        assert "Merged: 0" in body
        assert "Left: 0" in body


# ---------------------------------------------------------------------------
# alc.delivery — open_pr (against a fake `gh`; the real `gh` is never called)
# ---------------------------------------------------------------------------


class TestOpenPr:
    def test_reports_gracefully_when_gh_is_not_installed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        empty = tmp_path / "empty-bin"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))

        ok, message = open_pr(tmp_path, "main", "feature", "title", "body")

        assert ok is False
        assert "gh not installed" in message

    def test_opens_a_pr_via_the_fake_gh(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        state = _install_fake_gh(tmp_path, monkeypatch)
        repo = _make_git_repo(tmp_path)

        ok, message = open_pr(repo, "main", "feature", "my title", "my body")

        assert ok is True
        assert "https://" in message
        data = json.loads(state.read_text())
        assert data == {
            "base": "main",
            "head": "feature",
            "title": "my title",
            "body": "my body",
        }

    def test_gh_failure_is_reported_gracefully(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_gh(tmp_path, monkeypatch)
        monkeypatch.setenv("FAKE_GH_FAIL", "1")
        repo = _make_git_repo(tmp_path)

        ok, message = open_pr(repo, "main", "feature", "t", "b")

        assert ok is False
        assert "gh pr create failed" in message


# ---------------------------------------------------------------------------
# cmd_land — CLI wiring: --push / --pr, and the manifest `delivery` default
# ---------------------------------------------------------------------------


def _ns(**overrides) -> argparse.Namespace:
    defaults = {"branch": [], "all": False, "json": False, "push": False, "pr": False}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestCmdLandNoFlagsIsByteIdentical:
    def test_plain_land_never_prints_a_delivery_line(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/tick-aaa", "a.txt", "a\n", "feat(auto): a")
        monkeypatch.chdir(repo)

        assert cmd_land(_ns(all=True)) == 0

        captured = capsys.readouterr()
        assert "[land]" not in captured.out
        assert "[land]" not in captured.err

    def test_legacy_namespace_without_push_pr_attributes_still_works(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A Namespace built the way the pre-T8 tests build it (no push/pr keys)
        must not crash `cmd_land` — the additive flags are read via getattr."""
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/tick-aaa", "a.txt", "a\n", "feat(auto): a")
        monkeypatch.chdir(repo)

        legacy_ns = argparse.Namespace(branch=[], all=True, json=False)
        assert cmd_land(legacy_ns) == 0

    def test_push_flag_has_no_effect_on_the_listing_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _make_branch(repo, "alc/tick-aaa", "a.txt", "a\n", "feat(auto): a")
        monkeypatch.chdir(repo)

        assert cmd_land(_ns(push=True)) == 0  # no branch args, no --all -> listing path

        captured = capsys.readouterr()
        assert "alc/tick-aaa" in captured.out
        assert "[land]" not in captured.out


class TestCmdLandPush:
    def test_push_flag_pushes_the_landed_branch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        remote = _make_bare_remote(tmp_path)
        repo = _make_git_repo(tmp_path)
        _git(repo, "remote", "add", "origin", str(remote))
        _make_branch(repo, "alc/tick-aaa", "a.txt", "a\n", "feat(auto): a")
        monkeypatch.chdir(repo)

        assert cmd_land(_ns(all=True, push=True)) == 0

        out = capsys.readouterr().out
        assert "pushed main to origin" in out
        local_sha = _git(repo, "rev-parse", "main").stdout.strip()
        remote_sha = subprocess.run(
            ["git", "--git-dir", str(remote), "rev-parse", "main"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert remote_sha == local_sha

    def test_push_failure_never_changes_the_exit_code(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)  # no remote configured -> push will fail
        _make_branch(repo, "alc/tick-aaa", "a.txt", "a\n", "feat(auto): a")
        monkeypatch.chdir(repo)

        assert cmd_land(_ns(all=True, push=True)) == 0  # clean local land -> still 0

        err = capsys.readouterr().err
        assert "[land]" in err
        assert "failed" in err

    def test_push_flag_never_blocks_a_conflicted_land(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        remote = _make_bare_remote(tmp_path)
        repo = _make_git_repo(tmp_path)
        _git(repo, "remote", "add", "origin", str(remote))
        # Both branches rewrite seed.txt differently -> the second conflicts.
        _make_branch(repo, "alc/tick-aaa", "seed.txt", "from-a\n", "feat(auto): a")
        _make_branch(repo, "alc/tick-bbb", "seed.txt", "from-b\n", "feat(auto): b")
        monkeypatch.chdir(repo)

        assert cmd_land(_ns(all=True, push=True)) == 1  # unchanged: conflicts still exit 1

        out = capsys.readouterr().out
        assert "pushed main to origin" in out  # the clean part still got delivered


class TestCmdLandPr:
    def test_pr_flag_pushes_and_opens_a_review_worthy_pr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        remote = _make_bare_remote(tmp_path)
        repo = _make_git_repo(tmp_path)
        _git(repo, "remote", "add", "origin", str(remote))
        state = _install_fake_gh(tmp_path, monkeypatch)
        _make_branch(repo, "alc/tick-aaa", "a.txt", "a\n", "feat(auto): a")
        monkeypatch.chdir(repo)

        assert cmd_land(_ns(all=True, pr=True)) == 0

        out = capsys.readouterr().out
        assert "pushed main to origin" in out
        assert "https://" in out
        data = json.loads(state.read_text())
        assert data["head"] == "main"
        assert data["base"] == "main"
        assert "alc/tick-aaa" in data["body"]
        assert "## Checks" in data["body"]
        assert "## Scorecard" in data["body"]
        assert "## Changed files" in data["body"]

    def test_pr_flag_with_gh_missing_warns_but_never_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        remote = _make_bare_remote(tmp_path)
        repo = _make_git_repo(tmp_path)
        _git(repo, "remote", "add", "origin", str(remote))
        _make_branch(repo, "alc/tick-aaa", "a.txt", "a\n", "feat(auto): a")
        monkeypatch.chdir(repo)
        monkeypatch.setenv("PATH", _path_with_only_git(tmp_path))  # git yes, gh no

        assert cmd_land(_ns(all=True, pr=True)) == 0  # never fails the land

        captured = capsys.readouterr()
        assert "pushed main to origin" in captured.out  # push still happened
        assert "gh not installed" in captured.err

    def test_pr_flag_skips_the_pr_step_when_the_push_itself_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)  # no remote -> push fails
        _install_fake_gh(tmp_path, monkeypatch)
        _make_branch(repo, "alc/tick-aaa", "a.txt", "a\n", "feat(auto): a")
        monkeypatch.chdir(repo)

        assert cmd_land(_ns(all=True, pr=True)) == 0

        captured = capsys.readouterr()
        assert "https://" not in captured.out  # gh pr create was never even attempted


class TestCmdLandManifestDeliveryDefault:
    def test_manifest_push_mode_triggers_without_a_cli_flag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        remote = _make_bare_remote(tmp_path)
        repo = _make_git_repo(tmp_path)
        _git(repo, "remote", "add", "origin", str(remote))
        _write_delivery_manifest(repo, mode="push")
        _make_branch(repo, "alc/tick-aaa", "a.txt", "a\n", "feat(auto): a")
        monkeypatch.chdir(repo)

        assert cmd_land(_ns(all=True)) == 0  # no --push/--pr flag at all

        out = capsys.readouterr().out
        assert "pushed main to origin" in out

    def test_manifest_local_mode_stays_silent_like_the_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = _make_git_repo(tmp_path)
        _write_delivery_manifest(repo, mode="local")
        _make_branch(repo, "alc/tick-aaa", "a.txt", "a\n", "feat(auto): a")
        monkeypatch.chdir(repo)

        assert cmd_land(_ns(all=True)) == 0

        assert "[land]" not in capsys.readouterr().out

    def test_cli_push_flag_overrides_manifest_pr_mode_down_to_push(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        remote = _make_bare_remote(tmp_path)
        repo = _make_git_repo(tmp_path)
        _git(repo, "remote", "add", "origin", str(remote))
        _write_delivery_manifest(repo, mode="pr")
        _install_fake_gh(tmp_path, monkeypatch)
        _make_branch(repo, "alc/tick-aaa", "a.txt", "a\n", "feat(auto): a")
        monkeypatch.chdir(repo)

        assert cmd_land(_ns(all=True, push=True)) == 0

        out = capsys.readouterr().out
        assert "pushed main to origin" in out
        assert "https://" not in out  # --push overrides the manifest's pr mode

    def test_custom_remote_and_base_are_honored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        remote = _make_bare_remote(tmp_path)
        repo = _make_git_repo(tmp_path)
        _git(repo, "remote", "add", "upstream", str(remote))
        _write_delivery_manifest(repo, mode="push", remote="upstream")
        _make_branch(repo, "alc/tick-aaa", "a.txt", "a\n", "feat(auto): a")
        monkeypatch.chdir(repo)

        assert cmd_land(_ns(all=True)) == 0

        out = capsys.readouterr().out
        assert "pushed main to upstream" in out
