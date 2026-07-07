# test_cycle_standard.py — Hermetic tests for the Flow terminal commit (Part 2).
# Uses a real LOCAL git repo in tmp_path + a file-writing Mock engine; no model
# is ever called.
from __future__ import annotations

import subprocess
from pathlib import Path

from alc.commit import commit_workdir, has_non_alc_changes
from alc.flow import FlowRunner
from alc.intake import load_manifest
from alc.models import CommitSpec, FlowDefinition, FlowStage

# ---------------------------------------------------------------------------
# Inline operator layer + git helpers.
# ---------------------------------------------------------------------------

_MANIFEST = """\
version: 1
default_engine: mock
compute_tiers:
  standard:
    mock: mock-small
engines:
  mock:
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
1. Make the smallest change that satisfies the task.
"""

_CHORE_FAILING = """\
---
name: chore
purpose: Apply a low-risk, well-scoped maintenance change.
compute_tier: standard
checks:
  - name: always-fail
    command: ["false"]
---
# Workflow
1. Make the smallest change that satisfies the task.
"""


def _init_git_repo(repo: Path) -> None:
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@alc.local"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "ALC Test"],
        check=True,
        capture_output=True,
    )


def _commit_all(repo: Path, message: str) -> None:
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", message], check=True, capture_output=True
    )


def _build_repo(tmp_path: Path, chore: str = _CHORE) -> Path:
    """Build a git repo with a self-contained operator layer; return the repo path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    alc = repo / ".alc"
    (alc / "blueprints").mkdir(parents=True)
    (alc / "flows").mkdir(parents=True)
    (alc / "manifest.yaml").write_text(_MANIFEST)
    (alc / "blueprints" / "chore.md").write_text(chore)
    _commit_all(repo, "seed operator layer")
    return repo


def _git_log_subjects(repo: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), "log", "--format=%s"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.splitlines()


def _write_file_engine(rel_path: str, content: str = "written by engine\n"):
    """Return a MockEngine-like class that writes a file into the request workdir."""
    from alc.engine import Capabilities, EngineResult

    class _WriteFileEngine:
        name = "mock"

        def capabilities(self) -> Capabilities:
            return Capabilities()

        def health_check(self) -> bool:
            return True

        def run(self, request):
            (request.workdir / rel_path).write_text(content)
            return EngineResult(ok=True, output_text="[mock] wrote a file")

    return _WriteFileEngine


# ---------------------------------------------------------------------------
# commit_workdir — unit tests.
# ---------------------------------------------------------------------------


class TestCommitWorkdir:
    def test_commits_and_returns_sha(self, tmp_path: Path) -> None:
        repo = _build_repo(tmp_path)
        (repo / "new_file.txt").write_text("hello\n")

        sha = commit_workdir(repo, "feat(auto): add new file")

        assert sha is not None
        assert _git_log_subjects(repo)[0] == "feat(auto): add new file"

    def test_message_has_no_co_author(self, tmp_path: Path) -> None:
        repo = _build_repo(tmp_path)
        (repo / "new_file.txt").write_text("hello\n")

        commit_workdir(repo, "feat(auto): clean message")

        body = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%B"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "co-authored" not in body.lower()

    def test_excludes_alc_changes(self, tmp_path: Path) -> None:
        repo = _build_repo(tmp_path)
        # A change under .alc/ must NOT be staged/committed by commit_workdir.
        (repo / ".alc" / "scratch.txt").write_text("state\n")

        sha = commit_workdir(repo, "chore(cycle): demand")

        # Nothing outside .alc/ changed -> nothing to commit -> None, no new commit.
        assert sha is None
        assert _git_log_subjects(repo) == ["seed operator layer"]

    def test_excludes_alc_but_commits_other(self, tmp_path: Path) -> None:
        repo = _build_repo(tmp_path)
        (repo / ".alc" / "scratch.txt").write_text("state\n")
        (repo / "real.txt").write_text("real change\n")

        sha = commit_workdir(repo, "chore(cycle): demand")

        assert sha is not None
        # The committed tree includes real.txt but NOT the .alc/ scratch file.
        tree = subprocess.run(
            ["git", "-C", str(repo), "show", "--name-only", "--format=", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "real.txt" in tree
        assert ".alc/scratch.txt" not in tree

    def test_nothing_to_commit_returns_none(self, tmp_path: Path) -> None:
        repo = _build_repo(tmp_path)
        sha = commit_workdir(repo, "chore(cycle): demand")
        assert sha is None
        assert _git_log_subjects(repo) == ["seed operator layer"]


class TestHasNonAlcChanges:
    def test_clean_tree_is_false(self, tmp_path: Path) -> None:
        repo = _build_repo(tmp_path)
        assert has_non_alc_changes(repo) is False

    def test_alc_only_change_is_false(self, tmp_path: Path) -> None:
        repo = _build_repo(tmp_path)
        (repo / ".alc" / "scratch.txt").write_text("state\n")
        assert has_non_alc_changes(repo) is False

    def test_non_alc_change_is_true(self, tmp_path: Path) -> None:
        repo = _build_repo(tmp_path)
        (repo / "dirty.txt").write_text("uncommitted\n")
        assert has_non_alc_changes(repo) is True


# ---------------------------------------------------------------------------
# FlowRunner terminal commit — integration tests.
# ---------------------------------------------------------------------------


def _committing_flow() -> FlowDefinition:
    return FlowDefinition(
        name="demand",
        stages=[FlowStage(name="do", blueprint="chore")],
        commit=CommitSpec(enabled=True, message="feat(auto): {task}"),
    )


class TestFlowTerminalCommit:
    def test_commits_on_success(self, tmp_path: Path, monkeypatch) -> None:
        repo = _build_repo(tmp_path)
        engine = _write_file_engine("feature.txt")
        monkeypatch.setattr(
            "alc.runner.resolve_engine", lambda name, engines: engine()
        )

        manifest = load_manifest(repo / ".alc")
        runner = FlowRunner(manifest=manifest, operator_layer=repo / ".alc")
        report = runner.run(
            flow=_committing_flow(), task="ship the widget", engine_override="mock", workdir=repo
        )

        assert report.success is True
        assert report.commit_sha is not None

        subjects = _git_log_subjects(repo)
        # Exactly one new commit on top of the seed, with the templated message.
        assert subjects[0] == "feat(auto): ship the widget"
        assert len(subjects) == 2

        # The commit message carries NO Co-Authored-By trailer.
        body = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%B"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "co-authored" not in body.lower()

        # The committed tree includes the engine-written file.
        tree = subprocess.run(
            ["git", "-C", str(repo), "show", "--name-only", "--format=", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "feature.txt" in tree

    def test_no_commit_on_failure(self, tmp_path: Path, monkeypatch) -> None:
        # A failing check makes the stage (and flow) fail -> no commit.
        repo = _build_repo(tmp_path, chore=_CHORE_FAILING)
        engine = _write_file_engine("feature.txt")
        monkeypatch.setattr(
            "alc.runner.resolve_engine", lambda name, engines: engine()
        )

        manifest = load_manifest(repo / ".alc")
        runner = FlowRunner(manifest=manifest, operator_layer=repo / ".alc")
        report = runner.run(
            flow=_committing_flow(), task="ship the widget", engine_override="mock", workdir=repo
        )

        assert report.success is False
        assert report.commit_sha is None
        # git log unchanged (only the seed commit).
        assert _git_log_subjects(repo) == ["seed operator layer"]

    def test_clean_tree_guard_aborts(self, tmp_path: Path, monkeypatch) -> None:
        repo = _build_repo(tmp_path)
        # Pre-existing uncommitted non-.alc/ change in the shared workdir.
        (repo / "pre_existing.txt").write_text("unrelated work\n")

        engine = _write_file_engine("feature.txt")
        monkeypatch.setattr(
            "alc.runner.resolve_engine", lambda name, engines: engine()
        )

        manifest = load_manifest(repo / ".alc")
        runner = FlowRunner(manifest=manifest, operator_layer=repo / ".alc")
        report = runner.run(
            flow=_committing_flow(), task="ship the widget", engine_override="mock", workdir=repo
        )

        assert report.success is False
        assert report.commit_sha is None
        assert report.stages == []  # stages did not run
        # No commit created; the engine's feature.txt was never written.
        assert _git_log_subjects(repo) == ["seed operator layer"]
        assert not (repo / "feature.txt").exists()

    def test_backward_compat_no_commit_spec(self, tmp_path: Path, monkeypatch) -> None:
        """A blueprint-only flow with commit=None runs as before: no commit, no guard."""
        repo = _build_repo(tmp_path)
        # Pre-existing dirt must NOT abort a non-committing flow (no guard).
        (repo / "pre_existing.txt").write_text("unrelated work\n")

        engine = _write_file_engine("feature.txt")
        monkeypatch.setattr(
            "alc.runner.resolve_engine", lambda name, engines: engine()
        )

        flow = FlowDefinition(
            name="plain",
            stages=[FlowStage(name="do", blueprint="chore")],
        )
        manifest = load_manifest(repo / ".alc")
        runner = FlowRunner(manifest=manifest, operator_layer=repo / ".alc")
        report = runner.run(
            flow=flow, task="ship it", engine_override="mock", workdir=repo
        )

        assert report.success is True
        assert report.commit_sha is None
        # No terminal commit created despite success.
        assert _git_log_subjects(repo) == ["seed operator layer"]
