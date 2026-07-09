# test_cycle_standard.py — Hermetic tests for the Flow terminal commit (Part 2).
# Uses a real LOCAL git repo in tmp_path + a file-writing Mock engine; no model
# is ever called.
from __future__ import annotations

import subprocess
from pathlib import Path

from alc.commit import commit_workdir, has_non_alc_changes, revert_workdir
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

    def test_bad_commit_template_degrades_gracefully(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """A bad CommitSpec.message template never crashes a green flow.

        The terminal commit must still be created using the safe fallback message;
        the flow must succeed and FlowReport.commit_sha must be set.
        """
        repo = _build_repo(tmp_path)
        engine = _write_file_engine("feature.txt")
        monkeypatch.setattr(
            "alc.runner.resolve_engine", lambda name, engines: engine()
        )

        # A stray '{' is the classic operator mistake that raises ValueError.
        bad_flow = FlowDefinition(
            name="demand",
            stages=[FlowStage(name="do", blueprint="chore")],
            commit=CommitSpec(enabled=True, message="feat: {unknown_placeholder}"),
        )
        manifest = load_manifest(repo / ".alc")
        runner = FlowRunner(manifest=manifest, operator_layer=repo / ".alc")
        report = runner.run(
            flow=bad_flow, task="ship the widget", engine_override="mock", workdir=repo
        )

        # Flow must succeed despite the bad template.
        assert report.success is True
        assert report.commit_sha is not None

        # The fallback commit message must have been used.
        subjects = _git_log_subjects(repo)
        assert subjects[0] == "chore(cycle): demand"

        # A WARN must have been printed to stderr.
        captured = capsys.readouterr()
        assert "[WARN]" in captured.err


# ---------------------------------------------------------------------------
# Item 4: shared workdir hand-off — specialist stage sees prior stage's file.
# ---------------------------------------------------------------------------


class TestSharedWorkdirHandoff:
    """The whole point of the standard cycle: every stage shares one workdir,
    so a specialist stage can see files that an earlier stage wrote there."""

    def test_specialist_sees_prior_stage_file(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Stage 1 (blueprint) writes fileA into the workdir; stage 2 (specialist)
        observes that fileA exists in the same workdir. This validates the
        shared-workdir hand-off that makes the dev -> qa pattern work."""
        import yaml as _yaml

        from alc.engine import Capabilities, EngineResult

        # Build a repo with operator layer so commit-related code has a git root.
        repo = _build_repo(tmp_path)

        # Add a specialist definition to the operator layer.
        specialists_dir = repo / ".alc" / "specialists"
        specialists_dir.mkdir(exist_ok=True)
        (specialists_dir / "qa.yaml").write_text(
            _yaml.safe_dump({
                "name": "qa",
                "area": "quality assurance",
                "blueprint": "chore",
                "knowledge_path": ".alc/specialists/qa.knowledge.md",
            })
        )

        file_written_by_stage1 = repo / "handoff.txt"
        assert not file_written_by_stage1.exists(), "pre-condition: file absent before flow"

        # Track whether handoff.txt was visible when the qa specialist's engine ran.
        specialist_saw_file: list[bool] = []
        # Track blueprint stage writes.
        blueprint_wrote_file: list[bool] = []

        class _Stage1Engine:
            """Writes handoff.txt into the workdir (blueprint stage)."""
            name = "mock"

            def capabilities(self) -> Capabilities:
                return Capabilities()

            def health_check(self) -> bool:
                return True

            def run(self, request):
                path = request.workdir / "handoff.txt"
                path.write_text("from stage1\n")
                blueprint_wrote_file.append(path.exists())
                return EngineResult(ok=True, output_text="stage1-done")

        class _Stage2Engine:
            """Checks that handoff.txt is visible in its workdir (specialist stage)."""
            name = "mock"

            def capabilities(self) -> Capabilities:
                return Capabilities()

            def health_check(self) -> bool:
                return True

            def run(self, request):
                specialist_saw_file.append((request.workdir / "handoff.txt").exists())
                return EngineResult(ok=True, output_text="stage2-done")

        # resolve_engine is called once for stage1 (blueprint Act), then once or
        # more for stage2 (specialist Act + Learn). Use the specialist name in
        # the request.directive as a discriminator is fragile; instead use a
        # simple counter: first call returns Stage1, the rest return Stage2.
        call_count = [0]

        def _resolve(name, engines):
            call_count[0] += 1
            if call_count[0] == 1:
                return _Stage1Engine()
            return _Stage2Engine()

        monkeypatch.setattr("alc.runner.resolve_engine", _resolve)
        monkeypatch.setattr("alc.engines.registry.resolve_engine", _resolve)

        flow = FlowDefinition(
            name="dev-qa",
            stages=[
                FlowStage(name="dev", blueprint="chore"),
                FlowStage(name="qa", specialist="qa"),
            ],
        )

        manifest = load_manifest(repo / ".alc")
        runner = FlowRunner(manifest=manifest, operator_layer=repo / ".alc")
        report = runner.run(flow=flow, task="build and verify", engine_override="mock", workdir=repo)

        assert report.success is True, f"flow failed: {[s.output_text for s in report.stages]}"
        assert blueprint_wrote_file, "blueprint stage engine was never called"
        assert specialist_saw_file, "specialist stage engine was never called"
        # The specialist stage must have seen handoff.txt on every invocation.
        assert all(specialist_saw_file), (
            "specialist stage did NOT see the file written by the prior blueprint stage; "
            f"visibility per call: {specialist_saw_file}"
        )


# ---------------------------------------------------------------------------
# Item 5: end-to-end flow with specialist stage + commit.enabled in a git repo.
# ---------------------------------------------------------------------------


class TestSpecialistFlowWithCommit:
    """A flow whose stages include a specialist AND has commit.enabled creates a
    scoped commit on success, with FlowReport.commit_sha set."""

    def test_specialist_stage_and_commit(self, tmp_path: Path, monkeypatch) -> None:
        import yaml as _yaml

        from alc.engine import Capabilities, EngineResult

        repo = _build_repo(tmp_path)

        specialists_dir = repo / ".alc" / "specialists"
        specialists_dir.mkdir(exist_ok=True)
        (specialists_dir / "impl.yaml").write_text(
            _yaml.safe_dump({
                "name": "impl",
                "area": "implementation",
                "blueprint": "chore",
                "knowledge_path": ".alc/specialists/impl.knowledge.md",
            })
        )

        class _WritingEngine:
            name = "mock"

            def capabilities(self) -> Capabilities:
                return Capabilities()

            def health_check(self) -> bool:
                return True

            def run(self, request):
                (request.workdir / "output.txt").write_text("engine output\n")
                return EngineResult(ok=True, output_text="done")

        monkeypatch.setattr(
            "alc.runner.resolve_engine", lambda name, engines: _WritingEngine()
        )
        monkeypatch.setattr(
            "alc.engines.registry.resolve_engine",
            lambda name, engines: _WritingEngine(),
        )

        flow = FlowDefinition(
            name="demand",
            stages=[FlowStage(name="implement", specialist="impl")],
            commit=CommitSpec(enabled=True, message="feat(auto): {task}"),
        )

        manifest = load_manifest(repo / ".alc")
        runner = FlowRunner(manifest=manifest, operator_layer=repo / ".alc")
        report = runner.run(
            flow=flow, task="add output", engine_override="mock", workdir=repo
        )

        # Specialist stage ran successfully.
        assert report.success is True
        assert len(report.stages) == 1
        assert report.stages[0].success is True

        # Terminal commit was created.
        assert report.commit_sha is not None

        subjects = _git_log_subjects(repo)
        assert subjects[0] == "feat(auto): add output"

        # The commit object must have no Co-Authored-By trailer.
        body = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%B"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "co-authored" not in body.lower()


# ---------------------------------------------------------------------------
# Item 6: real co-author absence — the actual commit object, not just the string.
# ---------------------------------------------------------------------------


class TestRealCoAuthorAbsence:
    """commit_workdir must produce a commit object with no Co-Authored-By trailer.

    This test creates an actual commit in a real local git repo (not a mock) and
    inspects the raw commit body via ``git log``, so it catches any code path that
    might inject a trailer after the message is composed.
    """

    def test_commit_object_has_no_co_authored_by(self, tmp_path: Path) -> None:
        repo = _build_repo(tmp_path)
        (repo / "change.txt").write_text("real change\n")

        sha = commit_workdir(repo, "chore(auto): real commit")
        assert sha is not None, "commit_workdir must return a sha"

        body = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%B"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout

        # Check the raw commit body — no Co-Authored-By or co-authored in any casing.
        assert "co-authored" not in body.lower(), (
            f"commit object contains a Co-Authored-By trailer:\n{body}"
        )

    def test_flow_commit_object_has_no_co_authored_by(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The FlowRunner terminal commit object must also be co-author-free."""
        repo = _build_repo(tmp_path)
        engine = _write_file_engine("out.txt")
        monkeypatch.setattr(
            "alc.runner.resolve_engine", lambda name, engines: engine()
        )

        flow = FlowDefinition(
            name="demand",
            stages=[FlowStage(name="do", blueprint="chore")],
            commit=CommitSpec(enabled=True, message="feat(auto): {task}"),
        )
        manifest = load_manifest(repo / ".alc")
        runner = FlowRunner(manifest=manifest, operator_layer=repo / ".alc")
        report = runner.run(
            flow=flow, task="deploy", engine_override="mock", workdir=repo
        )

        assert report.commit_sha is not None

        body = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%B"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "co-authored" not in body.lower(), (
            f"flow terminal commit object contains a Co-Authored-By trailer:\n{body}"
        )


# ---------------------------------------------------------------------------
# Item 7: workdir-not-toplevel guard in commit_workdir / has_non_alc_changes.
# ---------------------------------------------------------------------------


class TestWorkdirToplevelGuard:
    """commit_workdir and has_non_alc_changes must operate against the git toplevel
    even when a subdirectory of the repo is passed as workdir."""

    def test_commit_workdir_uses_toplevel_when_subdir_passed(
        self, tmp_path: Path
    ) -> None:
        """Changes in the repo root are committed even when a subdir is given."""
        repo = _build_repo(tmp_path)
        subdir = repo / "src"
        subdir.mkdir()
        # Write the file at the repo root (not in subdir) so commit sees it.
        (repo / "toplevel_change.txt").write_text("change\n")

        # Pass the subdir — the guard must escalate to the toplevel.
        sha = commit_workdir(subdir, "chore: subdir call")

        assert sha is not None, (
            "commit_workdir passed a subdir must still commit by escalating to the toplevel"
        )
        subjects = _git_log_subjects(repo)
        assert subjects[0] == "chore: subdir call"

    def test_has_non_alc_changes_uses_toplevel_when_subdir_passed(
        self, tmp_path: Path
    ) -> None:
        """Dirty files at the repo root are detected even when a subdir is given."""
        repo = _build_repo(tmp_path)
        subdir = repo / "src"
        subdir.mkdir()
        (repo / "dirty.txt").write_text("uncommitted\n")

        assert has_non_alc_changes(subdir) is True

    def test_clean_repo_subdir_returns_false(self, tmp_path: Path) -> None:
        """A clean repo reports no non-alc changes regardless of which subdir is given."""
        repo = _build_repo(tmp_path)
        subdir = repo / "src"
        subdir.mkdir()
        # Write a tracked file so the subdir directory can be committed.
        (subdir / ".keep").write_text("")
        _commit_all(repo, "add src/")

        assert has_non_alc_changes(subdir) is False


# ---------------------------------------------------------------------------
# Item 8: gitignored .alc — dogfood scenario where .alc is in .gitignore.
# ---------------------------------------------------------------------------


class TestGitignoreAlc:
    """Reproduce the dogfood bug: when .alc is listed in .gitignore, the old
    ``git add -A -- ':(exclude).alc/'`` command printed an "ignored path" warning
    and exited 1, causing commit_workdir to return None even though non-.alc
    changes were correctly staged.

    The two-step fix (git add -A then git reset -- .alc/) must:
    - return a real sha (not None),
    - include the non-.alc files in the commit,
    - exclude .alc changes from the commit,
    - leave the tree clean for non-.alc files afterwards.
    """

    def _build_gitignored_alc_repo(self, tmp_path: Path) -> Path:
        """Build a repo where .alc is in .gitignore but has one tracked file."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        # Add .alc to .gitignore first so subsequent git add -A skips it.
        (repo / ".gitignore").write_text(".alc\n")

        # Force-add one .alc file so it becomes tracked (simulates a blueprint
        # that was committed before the .gitignore rule was added).
        (repo / ".alc").mkdir()
        tracked_alc = repo / ".alc" / "blueprints"
        tracked_alc.mkdir(parents=True)
        (tracked_alc / "x.md").write_text("original\n")
        subprocess.run(
            ["git", "-C", str(repo), "add", "-f", ".alc/blueprints/x.md"],
            check=True,
            capture_output=True,
        )
        (repo / "docs").mkdir()
        (repo / "docs" / "ROADMAP.md").write_text("initial roadmap\n")
        subprocess.run(
            ["git", "-C", str(repo), "add", "docs/ROADMAP.md"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "seed"],
            check=True,
            capture_output=True,
        )
        return repo

    def test_gitignored_alc_returns_sha_not_none(self, tmp_path: Path) -> None:
        """commit_workdir must succeed (return a sha) even when .alc is gitignored."""
        repo = self._build_gitignored_alc_repo(tmp_path)

        # Modify the tracked .alc file (should be excluded from commit).
        (repo / ".alc" / "blueprints" / "x.md").write_text("modified\n")
        # Add a non-.alc change (should be included in commit).
        (repo / "docs" / "ROADMAP.md").write_text("updated roadmap\n")
        (repo / "src").mkdir()
        (repo / "src" / "f.ts").write_text("export const x = 1;\n")

        sha = commit_workdir(repo, "feat(auto): x")

        assert sha is not None, (
            "commit_workdir returned None when .alc is gitignored; "
            "the two-step staging fix must handle this case"
        )

    def test_gitignored_alc_commit_includes_non_alc_files(self, tmp_path: Path) -> None:
        """The commit created under gitignored .alc must contain the non-.alc files."""
        repo = self._build_gitignored_alc_repo(tmp_path)

        (repo / ".alc" / "blueprints" / "x.md").write_text("modified\n")
        (repo / "docs" / "ROADMAP.md").write_text("updated roadmap\n")
        (repo / "src").mkdir()
        (repo / "src" / "f.ts").write_text("export const x = 1;\n")

        commit_workdir(repo, "feat(auto): x")

        tree = subprocess.run(
            ["git", "-C", str(repo), "show", "--name-only", "--format=", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "docs/ROADMAP.md" in tree
        assert "src/f.ts" in tree

    def test_gitignored_alc_commit_excludes_alc_change(self, tmp_path: Path) -> None:
        """The commit must NOT include the .alc modification even though the file is tracked."""
        repo = self._build_gitignored_alc_repo(tmp_path)

        (repo / ".alc" / "blueprints" / "x.md").write_text("modified\n")
        (repo / "docs" / "ROADMAP.md").write_text("updated roadmap\n")

        commit_workdir(repo, "feat(auto): x")

        tree = subprocess.run(
            ["git", "-C", str(repo), "show", "--name-only", "--format=", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert ".alc/blueprints/x.md" not in tree

    def test_gitignored_alc_commit_message_has_no_co_author(self, tmp_path: Path) -> None:
        """The commit message must carry no Co-Authored-By trailer."""
        repo = self._build_gitignored_alc_repo(tmp_path)

        (repo / "docs" / "ROADMAP.md").write_text("updated roadmap\n")

        commit_workdir(repo, "feat(auto): x")

        body = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%B"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "co-authored" not in body.lower()

    def test_gitignored_alc_has_non_alc_changes_false_after_commit(
        self, tmp_path: Path
    ) -> None:
        """After commit_workdir, has_non_alc_changes must be False (non-.alc tree is clean)."""
        repo = self._build_gitignored_alc_repo(tmp_path)

        (repo / ".alc" / "blueprints" / "x.md").write_text("modified\n")
        (repo / "docs" / "ROADMAP.md").write_text("updated roadmap\n")

        sha = commit_workdir(repo, "feat(auto): x")
        assert sha is not None

        # The .alc modification remains uncommitted (excluded), but the non-.alc
        # tree must now be clean so has_non_alc_changes returns False.
        assert has_non_alc_changes(repo) is False


# ---------------------------------------------------------------------------
# Item 9: atomic revert-on-failure for a committing Flow.
# ---------------------------------------------------------------------------


class TestFlowRevertOnFailure:
    """A committing Flow that fails must revert its own uncommitted non-.alc/ changes
    so the shared workdir is clean for the next demand.

    Tests A-D cover the revert mechanics; E confirms backward compat (commit=None).
    """

    def test_a_failed_flow_reverts_file(self, tmp_path: Path, monkeypatch) -> None:
        """A: engine writes feature.txt, check fails → feature.txt reverted, tree clean."""
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
        # Engine-written file must be gone after revert.
        assert not (repo / "feature.txt").exists()
        assert has_non_alc_changes(repo) is False
        # No new commit — only the seed remains.
        assert _git_log_subjects(repo) == ["seed operator layer"]

    def test_b_failed_flow_preserves_alc_dir(self, tmp_path: Path, monkeypatch) -> None:
        """B: pre-existing .alc/scratch.txt survives the revert; feature.txt reverted."""
        repo = _build_repo(tmp_path, chore=_CHORE_FAILING)
        engine = _write_file_engine("feature.txt")
        monkeypatch.setattr(
            "alc.runner.resolve_engine", lambda name, engines: engine()
        )

        # Pre-write a file under .alc/ that must survive the revert.
        scratch = repo / ".alc" / "scratch.txt"
        scratch.write_text("alc state\n")

        manifest = load_manifest(repo / ".alc")
        runner = FlowRunner(manifest=manifest, operator_layer=repo / ".alc")
        report = runner.run(
            flow=_committing_flow(), task="ship the widget", engine_override="mock", workdir=repo
        )

        assert report.success is False
        # feature.txt reverted, scratch.txt untouched.
        assert not (repo / "feature.txt").exists()
        assert scratch.exists()
        assert scratch.read_text() == "alc state\n"
        # Non-.alc tree is clean.
        assert has_non_alc_changes(repo) is False

    def test_c_revert_workdir_direct_gitignored_alc(self, tmp_path: Path) -> None:
        """C: call revert_workdir directly on a gitignored-.alc repo with mixed dirt.

        - Modified tracked docs/ROADMAP.md → restored to HEAD content.
        - Untracked src/f.ts → removed.
        - Tracked .alc/blueprints/x.md (modified) → LEFT modified (protected).
        - Untracked .alc/scratch.txt → LEFT (protected).
        - has_non_alc_changes → False after revert.
        """
        repo = TestGitignoreAlc()._build_gitignored_alc_repo(tmp_path)

        # Dirty the repo: non-.alc tracked file, untracked file, .alc tracked file, .alc untracked.
        (repo / "docs" / "ROADMAP.md").write_text("modified roadmap\n")
        (repo / "src").mkdir(exist_ok=True)
        (repo / "src" / "f.ts").write_text("export const x = 1;\n")
        (repo / ".alc" / "blueprints" / "x.md").write_text("modified\n")
        alc_scratch = repo / ".alc" / "scratch.txt"
        alc_scratch.write_text("alc scratch\n")

        result = revert_workdir(repo)

        assert result is True
        # Non-.alc tracked file restored.
        assert (repo / "docs" / "ROADMAP.md").read_text() == "initial roadmap\n"
        # Untracked non-.alc file removed.
        assert not (repo / "src" / "f.ts").exists()
        # .alc tracked file left modified (protected by exclude).
        assert (repo / ".alc" / "blueprints" / "x.md").read_text() == "modified\n"
        # .alc untracked file left (protected by exclude).
        assert alc_scratch.exists()
        assert alc_scratch.read_text() == "alc scratch\n"
        # Non-.alc portion of tree is clean.
        assert has_non_alc_changes(repo) is False

    def test_d_revert_workdir_after_git_add_a(self, tmp_path: Path) -> None:
        """D: same as C but git add -A before revert_workdir — reset -q prefix must undo stage."""
        repo = TestGitignoreAlc()._build_gitignored_alc_repo(tmp_path)

        (repo / "docs" / "ROADMAP.md").write_text("modified roadmap\n")
        (repo / "src").mkdir(exist_ok=True)
        (repo / "src" / "f.ts").write_text("export const x = 1;\n")
        (repo / ".alc" / "blueprints" / "x.md").write_text("modified\n")
        alc_scratch = repo / ".alc" / "scratch.txt"
        alc_scratch.write_text("alc scratch\n")

        # Stage everything (simulates a partial commit attempt or user action).
        subprocess.run(
            ["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True
        )

        result = revert_workdir(repo)

        assert result is True
        # Post-state must be identical to test_c.
        assert (repo / "docs" / "ROADMAP.md").read_text() == "initial roadmap\n"
        assert not (repo / "src" / "f.ts").exists()
        assert (repo / ".alc" / "blueprints" / "x.md").read_text() == "modified\n"
        assert alc_scratch.exists()
        assert has_non_alc_changes(repo) is False

    def test_e_non_committing_flow_does_not_revert(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """E: commit=None flow that fails must NOT revert (backward compat).

        feature.txt written by the engine must remain after the flow finishes.
        """
        repo = _build_repo(tmp_path, chore=_CHORE_FAILING)
        engine = _write_file_engine("feature.txt")
        monkeypatch.setattr(
            "alc.runner.resolve_engine", lambda name, engines: engine()
        )

        # A plain flow with no CommitSpec.
        flow = FlowDefinition(
            name="plain",
            stages=[FlowStage(name="do", blueprint="chore")],
        )
        manifest = load_manifest(repo / ".alc")
        runner = FlowRunner(manifest=manifest, operator_layer=repo / ".alc")
        report = runner.run(
            flow=flow, task="ship the widget", engine_override="mock", workdir=repo
        )

        assert report.success is False
        # Tree NOT reverted — backward compat.
        assert (repo / "feature.txt").exists()


# ---------------------------------------------------------------------------
# Knob D — CommitSpec.exclude adds paths; .alc/ stays a protected invariant.
# ---------------------------------------------------------------------------


class TestCommitExcludeKnob:
    def _two_file_engine(self):
        from alc.engine import Capabilities, EngineResult

        class _TwoFileEngine:
            name = "mock"

            def capabilities(self) -> Capabilities:
                return Capabilities()

            def health_check(self) -> bool:
                return True

            def run(self, request):
                (request.workdir / "keep.txt").write_text("keep\n")
                (request.workdir / "docs").mkdir(exist_ok=True)
                (request.workdir / "docs" / "note.txt").write_text("skip\n")
                (request.workdir / ".alc" / "scratch.txt").write_text("state\n")
                return EngineResult(ok=True, output_text="[mock] wrote files")

        return _TwoFileEngine()

    def test_operator_exclude_kept_out_while_alc_protected(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        repo = _build_repo(tmp_path)
        monkeypatch.setattr(
            "alc.runner.resolve_engine", lambda name, engines: self._two_file_engine()
        )
        flow = FlowDefinition(
            name="demand",
            stages=[FlowStage(name="do", blueprint="chore")],
            commit=CommitSpec(
                enabled=True, message="feat(auto): {task}", exclude=["docs/"]
            ),
        )
        manifest = load_manifest(repo / ".alc")
        runner = FlowRunner(manifest=manifest, operator_layer=repo / ".alc")
        report = runner.run(
            flow=flow, task="ship", engine_override="mock", workdir=repo
        )

        assert report.success is True
        assert report.commit_sha is not None
        tree = subprocess.run(
            ["git", "-C", str(repo), "show", "--name-only", "--format=", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "keep.txt" in tree               # committed
        assert "docs/note.txt" not in tree      # operator-excluded
        assert ".alc/scratch.txt" not in tree   # ALWAYS protected

    def test_unset_exclude_only_protects_alc(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # With exclude unset ([]) behavior is identical to today: everything but
        # .alc/ is committed (docs/note.txt lands, .alc/scratch.txt does not).
        repo = _build_repo(tmp_path)
        monkeypatch.setattr(
            "alc.runner.resolve_engine", lambda name, engines: self._two_file_engine()
        )
        flow = FlowDefinition(
            name="demand",
            stages=[FlowStage(name="do", blueprint="chore")],
            commit=CommitSpec(enabled=True, message="feat(auto): {task}"),
        )
        manifest = load_manifest(repo / ".alc")
        runner = FlowRunner(manifest=manifest, operator_layer=repo / ".alc")
        report = runner.run(
            flow=flow, task="ship", engine_override="mock", workdir=repo
        )

        assert report.success is True
        tree = subprocess.run(
            ["git", "-C", str(repo), "show", "--name-only", "--format=", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "keep.txt" in tree
        assert "docs/note.txt" in tree          # NOT excluded now
        assert ".alc/scratch.txt" not in tree   # still protected
