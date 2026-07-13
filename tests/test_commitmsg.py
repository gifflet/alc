# test_commitmsg.py — Unit tests for the commit-message generation module.
# Uses a fake engine; no real model or git repo is needed for most cases.
from __future__ import annotations

import subprocess
from pathlib import Path

from alc.commitmsg import generate_commit_message, make_commit_message_provider
from alc.engine import Capabilities, EngineResult
from alc.intake import load_manifest


# ---------------------------------------------------------------------------
# Fake engine helpers
# ---------------------------------------------------------------------------


class _FakeEngine:
    """Minimal engine that returns a canned output_text."""

    name = "mock"

    def __init__(self, output: str, ok: bool = True) -> None:
        self._output = output
        self._ok = ok

    def capabilities(self) -> Capabilities:
        return Capabilities()

    def health_check(self) -> bool:
        return True

    def run(self, request):
        return EngineResult(ok=self._ok, output_text=self._output)


class _RaisingEngine:
    """Engine that raises on every run() call."""

    name = "mock"

    def capabilities(self) -> Capabilities:
        return Capabilities()

    def health_check(self) -> bool:
        return True

    def run(self, request):
        raise RuntimeError("engine exploded")


# ---------------------------------------------------------------------------
# (a) Engine returns a valid Conventional Commits subject -> used
# ---------------------------------------------------------------------------


class TestGenerateCommitMessageValid:
    def test_valid_subject_is_returned(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        engine = _FakeEngine("feat(auth): add JWT refresh endpoint")

        result = generate_commit_message(
            diff="+ some code",
            engine=engine,
            model=None,
            workdir=operator_layer.parent,
            operator_layer=operator_layer,
            manifest=manifest,
            fallback="chore: fallback",
        )

        assert result == "feat(auth): add JWT refresh endpoint"

    def test_all_valid_types_accepted(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        valid_subjects = [
            "fix(ui): correct button alignment",
            "chore: update dependencies",
            "refactor(db): extract query builder",
            "docs: add API usage examples",
            "test(auth): cover token expiry path",
            "ci: switch to GitHub Actions",
            "perf(cache): use LRU eviction",
            "build: bump node version",
            "style: apply linter fixes",
            "revert: revert feat(x): y",
        ]
        for subject in valid_subjects:
            engine = _FakeEngine(subject)
            result = generate_commit_message(
                diff="+ code",
                engine=engine,
                model=None,
                workdir=operator_layer.parent,
                operator_layer=operator_layer,
                manifest=manifest,
                fallback="FALLBACK",
            )
            assert result == subject, f"Expected {subject!r} but got {result!r}"

    def test_subject_capped_at_100_chars(self, operator_layer: Path) -> None:
        long_subject = "feat(x): " + "a" * 200  # exceeds 100 chars
        manifest = load_manifest(operator_layer)
        engine = _FakeEngine(long_subject)

        result = generate_commit_message(
            diff="+ code",
            engine=engine,
            model=None,
            workdir=operator_layer.parent,
            operator_layer=operator_layer,
            manifest=manifest,
            fallback="FALLBACK",
        )

        assert len(result) <= 100
        assert result.startswith("feat(x):")


# ---------------------------------------------------------------------------
# (b) Engine returns non-Conventional output -> fallback
# ---------------------------------------------------------------------------


class TestGenerateCommitMessageFallback:
    def test_non_conventional_output_returns_fallback(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        engine = _FakeEngine("[mock] applied directive")

        result = generate_commit_message(
            diff="+ some code",
            engine=engine,
            model=None,
            workdir=operator_layer.parent,
            operator_layer=operator_layer,
            manifest=manifest,
            fallback="chore(auto): my-flow",
        )

        assert result == "chore(auto): my-flow"

    def test_empty_engine_output_returns_fallback(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        engine = _FakeEngine("")

        result = generate_commit_message(
            diff="+ code",
            engine=engine,
            model=None,
            workdir=operator_layer.parent,
            operator_layer=operator_layer,
            manifest=manifest,
            fallback="FALLBACK",
        )

        assert result == "FALLBACK"

    def test_prose_not_conventional_returns_fallback(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        engine = _FakeEngine("Added a new feature to handle user sessions.")

        result = generate_commit_message(
            diff="+ code",
            engine=engine,
            model=None,
            workdir=operator_layer.parent,
            operator_layer=operator_layer,
            manifest=manifest,
            fallback="FALLBACK",
        )

        assert result == "FALLBACK"


# ---------------------------------------------------------------------------
# (c) Empty diff -> fallback (no engine call needed)
# ---------------------------------------------------------------------------


class TestGenerateCommitMessageEmptyDiff:
    def test_empty_string_returns_fallback(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        engine = _FakeEngine("feat(x): should not be called")

        result = generate_commit_message(
            diff="",
            engine=engine,
            model=None,
            workdir=operator_layer.parent,
            operator_layer=operator_layer,
            manifest=manifest,
            fallback="FALLBACK",
        )

        assert result == "FALLBACK"

    def test_whitespace_only_returns_fallback(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        engine = _FakeEngine("feat(x): should not be called")

        result = generate_commit_message(
            diff="   \n\t  ",
            engine=engine,
            model=None,
            workdir=operator_layer.parent,
            operator_layer=operator_layer,
            manifest=manifest,
            fallback="FALLBACK",
        )

        assert result == "FALLBACK"


# ---------------------------------------------------------------------------
# (d) Engine raises -> fallback (never propagates)
# ---------------------------------------------------------------------------


class TestGenerateCommitMessageEngineRaises:
    def test_engine_exception_returns_fallback(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        engine = _RaisingEngine()

        result = generate_commit_message(
            diff="+ some code",
            engine=engine,
            model=None,
            workdir=operator_layer.parent,
            operator_layer=operator_layer,
            manifest=manifest,
            fallback="FALLBACK",
        )

        assert result == "FALLBACK"


# ---------------------------------------------------------------------------
# (e) Sanitization: backticks/quotes/Co-Authored-By/multi-line -> first clean line
# ---------------------------------------------------------------------------


class TestGenerateCommitMessageSanitize:
    def test_leading_backticks_stripped(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        engine = _FakeEngine("`feat(x): remove debug logging`")

        result = generate_commit_message(
            diff="+ code",
            engine=engine,
            model=None,
            workdir=operator_layer.parent,
            operator_layer=operator_layer,
            manifest=manifest,
            fallback="FALLBACK",
        )

        assert result == "feat(x): remove debug logging"

    def test_leading_quotes_stripped(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        engine = _FakeEngine('"fix(db): prevent null pointer"')

        result = generate_commit_message(
            diff="+ code",
            engine=engine,
            model=None,
            workdir=operator_layer.parent,
            operator_layer=operator_layer,
            manifest=manifest,
            fallback="FALLBACK",
        )

        assert result == "fix(db): prevent null pointer"

    def test_co_authored_by_line_skipped(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        # co-authored-by line before the subject -> subject is extracted
        engine = _FakeEngine("Co-Authored-By: bot\nfeat(api): expose health endpoint")

        result = generate_commit_message(
            diff="+ code",
            engine=engine,
            model=None,
            workdir=operator_layer.parent,
            operator_layer=operator_layer,
            manifest=manifest,
            fallback="FALLBACK",
        )

        assert result == "feat(api): expose health endpoint"

    def test_only_first_nonempty_line_used(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        engine = _FakeEngine(
            "feat(ui): add dark mode\n\nThis is a body paragraph.\nAnd another line."
        )

        result = generate_commit_message(
            diff="+ code",
            engine=engine,
            model=None,
            workdir=operator_layer.parent,
            operator_layer=operator_layer,
            manifest=manifest,
            fallback="FALLBACK",
        )

        assert result == "feat(ui): add dark mode"


# ---------------------------------------------------------------------------
# make_commit_message_provider
# ---------------------------------------------------------------------------


class TestMakeCommitMessageProvider:
    def test_returns_none_when_disabled(self, operator_layer: Path) -> None:
        import yaml

        manifest_text = (operator_layer / "manifest.yaml").read_text()
        manifest_data = yaml.safe_load(manifest_text)
        manifest_data["generate_commit_messages"] = False
        (operator_layer / "manifest.yaml").write_text(yaml.safe_dump(manifest_data))

        manifest = load_manifest(operator_layer)
        provider = make_commit_message_provider(
            manifest=manifest,
            operator_layer=operator_layer,
            workdir=operator_layer.parent,
            fallback="FALLBACK",
        )

        assert provider is None

    def test_returns_callable_when_enabled(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        provider = make_commit_message_provider(
            manifest=manifest,
            operator_layer=operator_layer,
            workdir=operator_layer.parent,
            fallback="FALLBACK",
        )

        assert provider is not None
        assert callable(provider)

    def test_provider_returns_fallback_for_empty_diff(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        provider = make_commit_message_provider(
            manifest=manifest,
            operator_layer=operator_layer,
            workdir=operator_layer.parent,
            fallback="chore: my fallback",
        )
        assert provider is not None

        result = provider("")  # empty diff -> fallback
        assert result == "chore: my fallback"


# ---------------------------------------------------------------------------
# Worktree double-format bug fix
# ---------------------------------------------------------------------------


def _init_git_repo(repo: Path) -> None:
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@alc.local"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "ALC Test"],
        check=True, capture_output=True,
    )
    (repo / "seed.txt").write_text("x\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "init"], check=True, capture_output=True
    )


class TestWorktreeDoubleFormatBugFix:
    """IsolatedWorktree must handle commit_message strings that already contain
    literal braces (e.g. task text with JSON) without crashing or falling back."""

    def test_message_with_literal_braces_does_not_crash(self, tmp_path: Path) -> None:
        from alc.worktree import IsolatedWorktree

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        # A message that has already had {name}/{task} substituted but still
        # contains literal braces from the task text (e.g. JSON in a task).
        message_with_braces = "feat(auto): implement {name, version} endpoint"
        wt = IsolatedWorktree(repo, "test", commit_message=message_with_braces)
        with wt as wt_path:
            (wt_path / "feature.txt").write_text("implemented\n")

        assert wt.committed is True
        # Verify git commit message was exactly the literal string (no fallback).
        # -1 ensures only the HEAD commit of the branch is read (not the seed commit).
        log = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%s", wt.branch],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert log == message_with_braces

        subprocess.run(
            ["git", "-C", str(repo), "branch", "-D", wt.branch], capture_output=True
        )

    def test_branch_placeholder_is_filled(self, tmp_path: Path) -> None:
        from alc.worktree import IsolatedWorktree

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        wt = IsolatedWorktree(repo, "mytest", commit_message="alc: {branch}")
        with wt as wt_path:
            (wt_path / "out.txt").write_text("output\n")

        assert wt.committed is True
        # -1 ensures only the HEAD commit of the branch is read (not the seed commit).
        log = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%s", wt.branch],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        # {branch} should be replaced with the actual branch name.
        assert log == f"alc: {wt.branch}"

        subprocess.run(
            ["git", "-C", str(repo), "branch", "-D", wt.branch], capture_output=True
        )


# ---------------------------------------------------------------------------
# Integration: fanout with a provider that returns a valid Conventional subject
# ---------------------------------------------------------------------------


_MANIFEST_YAML = """\
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

_CHORE_BP = """\
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

_COMMITTING_FLOW = """\
name: demand
description: A committing flow for commit-message generation tests.
stages:
  - name: do
    blueprint: chore
commit:
  enabled: true
  message: "feat(auto): {task}"
"""


def _commit_all(repo: Path, message: str) -> None:
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", message], check=True, capture_output=True
    )


class TestFanoutCommitMessageProviderIntegration:
    """A committing flow via run_fanout with a provider that returns a valid CC subject
    must land that subject as the branch commit message."""

    def test_provider_subject_used_as_commit_message(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from alc.engine import Capabilities, EngineResult
        from alc.fanout import run_fanout

        # The agent engine writes a file during its turn.
        class _AgentEngine:
            name = "mock"

            def capabilities(self) -> Capabilities:
                return Capabilities()

            def health_check(self) -> bool:
                return True

            def run(self, request):
                (request.workdir / "feat.txt").write_text("new feature\n")
                return EngineResult(ok=True, output_text="[mock] wrote feat.txt")

        # The commit-message engine always returns a valid CC subject.
        class _CommitEngine:
            name = "mock"

            def capabilities(self) -> Capabilities:
                return Capabilities()

            def health_check(self) -> bool:
                return True

            def run(self, request):
                return EngineResult(ok=True, output_text="feat(x): add new feature")

        agent_instance = _AgentEngine()
        commit_instance = _CommitEngine()

        monkeypatch.setattr(
            "alc.runner.resolve_engine", lambda name, cfg: agent_instance
        )
        monkeypatch.setattr(
            "alc.commitmsg.resolve_engine", lambda name, cfg: commit_instance
        )

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        alc = repo / ".alc"
        (alc / "blueprints").mkdir(parents=True)
        (alc / "flows").mkdir(parents=True)
        (alc / "manifest.yaml").write_text(_MANIFEST_YAML)
        (alc / "blueprints" / "chore.md").write_text(_CHORE_BP)
        (alc / "flows" / "demand.yaml").write_text(_COMMITTING_FLOW)
        _commit_all(repo, "seed")

        manifest = load_manifest(alc)
        units = [{"kind": "flow", "name": "demand", "task": "add new feature"}]
        report = run_fanout(manifest, alc, units, max_workers=1)

        assert report.success is True, report.units[0].error
        unit = report.units[0]
        assert unit.branch is not None

        # -1 reads only the HEAD commit of the branch (not the seed).
        log = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%s", unit.branch],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        # The generated Conventional Commits subject must be the commit message.
        assert log == "feat(x): add new feature"
