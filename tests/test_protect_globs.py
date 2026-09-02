# test_protect_globs.py — Hermetic tests for `protect: [globs]`:
# a deterministic, engine-agnostic guard that turns a protected-path edit into a
# synthetic failed check feeding the existing repair addendum.
#
# (a) Blueprint.protect front-matter round-trip.
# (b) AssuranceLoop: a protected-path hit becomes a synthetic failed check that
#     drives a repair turn, using a caller-supplied `changed_files` callable —
#     the loop itself never touches git.
# (c) runner.py wiring: execute_mandate binds real git snapshots into the
#     callable, and degrades to a silent no-op outside a repo / without git.
# (d) Policy Gate rule validating the declared globs.
from __future__ import annotations

import subprocess
from pathlib import Path

from alc.assurance import AssuranceLoop
from alc.engine import Capabilities, EngineRequest, EngineResult
from alc.engines.mock import MockEngine
from alc.intake import load_blueprint
from alc.models import Blueprint, Check, Manifest
from alc.policy import has_errors, lint
from alc.runner import execute_mandate
from alc.verifier import Verifier

_MINIMAL_MANIFEST = Manifest(
    version=1,
    default_engine="mock",
    compute_tiers={"standard": {"mock": "mock-small"}},
    engines={"mock": {"type": "mock"}},
)


# ---------------------------------------------------------------------------
# (a) Front-matter round-trip
# ---------------------------------------------------------------------------


class TestLoadBlueprintProtect:
    def test_protect_round_trip(self, tmp_path: Path) -> None:
        blueprints_dir = tmp_path / "blueprints"
        blueprints_dir.mkdir()
        (blueprints_dir / "refactor.md").write_text(
            """\
---
name: refactor
purpose: Simplify behavior-preservingly.
compute_tier: standard
protect: ["tests/**", "test/**"]
checks:
  - name: smoke
    command: ["true"]
---
# Workflow
Simplify.
"""
        )
        bp = load_blueprint(blueprints_dir, "refactor")
        assert bp.protect == ["tests/**", "test/**"]

    def test_absent_protect_is_empty_list(self, tmp_path: Path) -> None:
        blueprints_dir = tmp_path / "blueprints"
        blueprints_dir.mkdir()
        (blueprints_dir / "chore.md").write_text(
            """\
---
name: chore
purpose: A standard chore blueprint.
compute_tier: standard
checks:
  - name: smoke
    command: ["true"]
---
# Workflow
Do the task.
"""
        )
        bp = load_blueprint(blueprints_dir, "chore")
        assert bp.protect == []


# ---------------------------------------------------------------------------
# (b) AssuranceLoop: synthetic failed check + repair, driven by a plain callable
# ---------------------------------------------------------------------------


def _request(workdir: Path) -> EngineRequest:
    return EngineRequest(directive="# Single-Mandate refactor\nSimplify.", workdir=workdir)


def _always_passing_check() -> list[Check]:
    return [Check(name="smoke", command=["true"])]


class TestAssuranceLoopProtect:
    def test_protected_path_hit_fails_the_attempt_and_drives_a_repair(
        self, tmp_path: Path
    ) -> None:
        # attempt 0 "touches" tests/foo.py; attempt 1 does not.
        touched_per_attempt = [["tests/foo.py"], []]
        calls = {"n": 0}

        def _changed_files() -> list[str]:
            idx = min(calls["n"], len(touched_per_attempt) - 1)
            calls["n"] += 1
            return touched_per_attempt[idx]

        loop = AssuranceLoop(
            engine=MockEngine(),  # never writes real files; the callable fakes "changed"
            verifier=Verifier(),
            max_repairs=1,
            protect=["tests/**"],
            changed_files=_changed_files,
        )

        report = loop.run(_request(tmp_path), checks=_always_passing_check())

        assert report.success is True
        assert len(report.attempts) == 2
        assert "protected-paths" in report.attempts[0].failed_checks
        assert report.attempts[1].failed_checks == []

    def test_repair_addendum_names_the_protected_path(self, tmp_path: Path) -> None:
        seen_directives: list[str] = []

        class _RecordingEngine:
            name = "mock"

            def capabilities(self) -> Capabilities:
                return Capabilities()

            def health_check(self) -> bool:
                return True

            def run(self, request: EngineRequest) -> EngineResult:
                seen_directives.append(request.directive)
                return EngineResult(ok=True, output_text="[mock] applied directive")

        loop = AssuranceLoop(
            engine=_RecordingEngine(),
            verifier=Verifier(),
            max_repairs=1,
            protect=["tests/**"],
            changed_files=lambda: ["tests/foo.py"],
        )
        loop.run(_request(tmp_path), checks=_always_passing_check())

        assert len(seen_directives) == 2
        assert "tests/foo.py" in seen_directives[1]
        assert "protected-paths" in seen_directives[1]

    def test_no_hit_never_touches_a_passing_run(self, tmp_path: Path) -> None:
        loop = AssuranceLoop(
            engine=MockEngine(),
            verifier=Verifier(),
            max_repairs=3,
            protect=["tests/**"],
            changed_files=lambda: ["src/app.py"],
        )
        report = loop.run(_request(tmp_path), checks=_always_passing_check())

        assert report.success is True
        assert len(report.attempts) == 1
        assert report.attempts[0].failed_checks == []

    def test_empty_protect_is_a_no_op_even_with_a_changed_files_callable(
        self, tmp_path: Path
    ) -> None:
        loop = AssuranceLoop(
            engine=MockEngine(),
            verifier=Verifier(),
            max_repairs=3,
            protect=[],
            changed_files=lambda: ["tests/foo.py"],
        )
        report = loop.run(_request(tmp_path), checks=_always_passing_check())

        assert report.success is True
        assert report.attempts[0].failed_checks == []

    def test_no_changed_files_callable_is_a_no_op(self, tmp_path: Path) -> None:
        loop = AssuranceLoop(
            engine=MockEngine(), verifier=Verifier(), max_repairs=3, protect=["tests/**"]
        )
        report = loop.run(_request(tmp_path), checks=_always_passing_check())

        assert report.success is True
        assert report.attempts[0].failed_checks == []


# ---------------------------------------------------------------------------
# (c) runner.py wiring: real git snapshots, degrading gracefully without git
# ---------------------------------------------------------------------------


def _init_git_repo(repo: Path) -> None:
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"], check=True, capture_output=True
    )
    seed = repo / "seed.txt"
    seed.write_text("seed")
    subprocess.run(["git", "-C", str(repo), "add", "seed.txt"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "seed"], check=True, capture_output=True
    )


class TestExecuteMandateProtectIntegration:
    def test_writing_a_protected_path_drives_a_repair_turn(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _init_git_repo(tmp_path)

        # `changed_files` is CUMULATIVE since the run started, so a genuine
        # repair must revert the protected file, not merely avoid re-touching
        # it — attempt 1 deletes what attempt 0 wrote, then writes elsewhere.
        class _ScriptedEngine:
            name = "mock"

            def __init__(self) -> None:
                self._call_index = 0

            def capabilities(self) -> Capabilities:
                return Capabilities()

            def health_check(self) -> bool:
                return True

            def run(self, request: EngineRequest) -> EngineResult:
                if self._call_index == 0:
                    dst = request.workdir / "tests" / "new_test.py"
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_text("bad\n")
                else:
                    (request.workdir / "tests" / "new_test.py").unlink()
                    dst = request.workdir / "src" / "app.py"
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_text("good\n")
                self._call_index += 1
                return EngineResult(ok=True, output_text="[mock] wrote files")

        engine = _ScriptedEngine()
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine)

        bp = Blueprint(
            name="refactor",
            purpose="Simplify.",
            workflow="# w",
            checks=[Check(name="smoke", command=["true"])],
            protect=["tests/**"],
            max_repairs=1,
        )
        report = execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=bp,
            directive="# test\nsimplify",
            engine_override="mock",
            workdir=tmp_path,
        )

        assert len(report.attempts) == 2
        assert "protected-paths" in report.attempts[0].failed_checks
        assert report.attempts[1].failed_checks == []

    def test_outside_git_repo_protect_is_a_silent_no_op(self, tmp_path: Path) -> None:
        # tmp_path is NOT a git repo — protect must never raise or block the run.
        bp = Blueprint(
            name="refactor",
            purpose="Simplify.",
            workflow="# w",
            checks=[Check(name="smoke", command=["true"])],
            protect=["tests/**"],
        )
        report = execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=bp,
            directive="# test\nsimplify",
            engine_override="mock",
            workdir=tmp_path,
        )
        assert report.success is True

    def test_untouched_protected_glob_does_not_affect_a_clean_run(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _init_git_repo(tmp_path)
        engine = _write_files_engine({"src/app.py": "good\n"})
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine())

        bp = Blueprint(
            name="refactor",
            purpose="Simplify.",
            workflow="# w",
            checks=[Check(name="smoke", command=["true"])],
            protect=["tests/**"],
        )
        report = execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=bp,
            directive="# test\nsimplify",
            engine_override="mock",
            workdir=tmp_path,
        )
        assert report.success is True
        assert len(report.attempts) == 1


def _write_files_engine(files: dict[str, str]):
    class _WriteFilesEngine:
        name = "mock"

        def capabilities(self) -> Capabilities:
            return Capabilities()

        def health_check(self) -> bool:
            return True

        def run(self, request: EngineRequest) -> EngineResult:
            for rel_path, content in files.items():
                dst = request.workdir / rel_path
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(content)
            return EngineResult(ok=True, output_text="[mock] wrote files")

    return _WriteFilesEngine


# ---------------------------------------------------------------------------
# (d) Policy Gate: blueprint-protect-globs-valid
# ---------------------------------------------------------------------------


class TestPolicyProtectGlobsValid:
    def _bp(self, protect: list[str]) -> Blueprint:
        return Blueprint(
            name="refactor",
            purpose="p",
            workflow="w",
            checks=[Check(name="smoke", command=["true"])],
            protect=protect,
        )

    def test_relative_globs_yield_no_violation(self) -> None:
        violations = lint(_MINIMAL_MANIFEST, [self._bp(["tests/**", "test/**"])])
        assert [v for v in violations if v.rule == "blueprint-protect-globs-valid"] == []

    def test_absolute_glob_is_error(self) -> None:
        violations = lint(_MINIMAL_MANIFEST, [self._bp(["/etc/passwd"])])
        matching = [v for v in violations if v.rule == "blueprint-protect-globs-valid"]
        assert len(matching) == 1
        assert matching[0].severity == "error"
        assert has_errors(violations)

    def test_parent_escaping_glob_is_error(self) -> None:
        violations = lint(_MINIMAL_MANIFEST, [self._bp(["../outside/**"])])
        matching = [v for v in violations if v.rule == "blueprint-protect-globs-valid"]
        assert len(matching) == 1
        assert matching[0].severity == "error"

    def test_empty_string_glob_is_error(self) -> None:
        violations = lint(_MINIMAL_MANIFEST, [self._bp([""])])
        matching = [v for v in violations if v.rule == "blueprint-protect-globs-valid"]
        assert len(matching) == 1

    def test_empty_protect_list_yields_no_violation(self) -> None:
        violations = lint(_MINIMAL_MANIFEST, [self._bp([])])
        assert [v for v in violations if v.rule == "blueprint-protect-globs-valid"] == []
