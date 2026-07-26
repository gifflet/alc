# test_check_config_guard.py — Hermetic tests for the `check-config-integrity`
# guard (dogfooding gap #10): a deterministic, engine-agnostic guard that turns an
# Act's edit to a CHECK-DEFINING file (the "law" a run must pass) into a synthetic
# failed check feeding the existing repair addendum — exactly parallel to
# `protect:`'s `protected-paths` guard.
#
# The move it closes: an engine that cannot make the code pass can make the LAW
# pass instead (widen an eslint ignore, delete a ruff rule, rewrite a `test`
# script to `true`) and land a run that proved nothing. The guard makes that
# tamper-EVIDENT (the operator always sees a run that touched check config) and
# tamper-RESISTANT (a run that silently weakens a check fails, so never auto-lands).
#
# (unit) The pure detector: basename patterns, the two dep-manifest-AND-check-config
#        files (package.json scripts / pyproject [tool]), and check-referenced files.
# (b) AssuranceLoop: a hit becomes a synthetic failed check driving a repair, via a
#     caller-supplied guard callable — the loop itself never touches git or content.
# (c) runner.py wiring: execute_mandate binds real git snapshots into the callable,
#     opts out on allow_check_config, and degrades to a no-op outside a repo.
# (a) Blueprint.allow_check_config front-matter round-trip + RunReport field.
# (d) Policy Gate rule surfacing every Blueprint that waives the guard.
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from alc.assurance import AssuranceLoop
from alc.checkconfig import (
    check_referenced_files,
    detect_check_config_edits,
    snapshot_check_manifests,
)
from alc.engine import Capabilities, EngineRequest, EngineResult
from alc.engines.mock import MockEngine
from alc.events import bind_run_log
from alc.intake import load_blueprint
from alc.models import Blueprint, Check, Manifest, RunReport, Scorecard
from alc.policy import has_errors, lint
from alc.runner import execute_mandate
from alc.verifier import CheckResult, Verifier

_MINIMAL_MANIFEST = Manifest(
    version=1,
    default_engine="mock",
    compute_tiers={"standard": {"mock": "mock-small"}},
    engines={"mock": {"type": "mock"}},
)


def _empty_snapshot() -> dict:
    """A snapshot for a workdir with neither dep-manifest present."""
    return {"package.json": None, "pyproject.toml": None}


# ---------------------------------------------------------------------------
# (unit) The pure detector — no git, no loop, no content beyond the workdir.
# ---------------------------------------------------------------------------


class TestBasenamePatterns:
    def test_root_config_is_a_hit(self, tmp_path: Path) -> None:
        hits = detect_check_config_edits(
            ["eslint.config.mjs"], tmp_path, _empty_snapshot(), set()
        )
        assert len(hits) == 1
        assert "eslint.config.mjs" in hits[0]

    def test_nested_config_is_a_hit(self, tmp_path: Path) -> None:
        # Matched by BASENAME — a tool reads its config wherever it sits, so a
        # nested copy is caught as readily as a root one.
        hits = detect_check_config_edits(
            ["packages/web/.eslintrc.json"], tmp_path, _empty_snapshot(), set()
        )
        assert len(hits) == 1
        assert "packages/web/.eslintrc.json" in hits[0]

    def test_task_file_and_ruff_toml_are_hits(self, tmp_path: Path) -> None:
        hits = detect_check_config_edits(
            ["Makefile", "ruff.toml"], tmp_path, _empty_snapshot(), set()
        )
        assert len(hits) == 2

    def test_source_file_is_not_a_hit(self, tmp_path: Path) -> None:
        assert (
            detect_check_config_edits(["src/app.py"], tmp_path, _empty_snapshot(), set())
            == []
        )

    def test_alc_path_is_filtered_even_when_a_pattern_matches(
        self, tmp_path: Path
    ) -> None:
        # .alc/ is already always-protected — never double-reported here even when
        # its basename ("Makefile") would otherwise match a pattern.
        assert (
            detect_check_config_edits(
                [".alc/Makefile"], tmp_path, _empty_snapshot(), set()
            )
            == []
        )


class TestPackageJsonScripts:
    def test_scripts_change_is_a_hit(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "true"}}))
        snapshot = {"package.json": {"test": "vitest"}, "pyproject.toml": None}
        hits = detect_check_config_edits(["package.json"], tmp_path, snapshot, set())
        assert len(hits) == 1
        assert "package.json" in hits[0]

    def test_dependency_only_change_is_clean(self, tmp_path: Path) -> None:
        # scripts unchanged, only dependencies moved — the check recipes are intact.
        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"test": "vitest"}, "dependencies": {"left-pad": "^2"}})
        )
        snapshot = {"package.json": {"test": "vitest"}, "pyproject.toml": None}
        assert detect_check_config_edits(["package.json"], tmp_path, snapshot, set()) == []

    def test_appeared_scripts_is_a_hit(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest"}}))
        snapshot = {"package.json": None, "pyproject.toml": None}
        hits = detect_check_config_edits(["package.json"], tmp_path, snapshot, set())
        assert len(hits) == 1

    def test_unparseable_after_is_a_hit(self, tmp_path: Path) -> None:
        # A config that can no longer be read can no longer be trusted -> a hit.
        (tmp_path / "package.json").write_text("{not valid json")
        snapshot = {"package.json": {"test": "vitest"}, "pyproject.toml": None}
        hits = detect_check_config_edits(["package.json"], tmp_path, snapshot, set())
        assert len(hits) == 1


class TestPyprojectToolTable:
    def test_tool_table_change_is_a_hit(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nselect = []\n")
        snapshot = {"package.json": None, "pyproject.toml": {"ruff": {"select": ["E"]}}}
        hits = detect_check_config_edits(["pyproject.toml"], tmp_path, snapshot, set())
        assert len(hits) == 1
        assert "pyproject.toml" in hits[0]

    def test_project_dependency_bump_is_clean(self, tmp_path: Path) -> None:
        # [project].dependencies moved but the [tool] table is byte-identical.
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\ndependencies = ["requests>=2"]\n'
            '[tool.ruff]\nselect = ["E"]\n'
        )
        snapshot = {"package.json": None, "pyproject.toml": {"ruff": {"select": ["E"]}}}
        assert detect_check_config_edits(["pyproject.toml"], tmp_path, snapshot, set()) == []


class TestCheckReferencedFiles:
    def test_argv_referenced_script_is_collected(self, tmp_path: Path) -> None:
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "bench.py").write_text("print(1)\n")
        checks = [Check(name="bench", command=["python", "scripts/bench.py"])]
        assert "scripts/bench.py" in check_referenced_files(checks, tmp_path)

    def test_binary_on_path_is_not_collected(self, tmp_path: Path) -> None:
        checks = [Check(name="smoke", command=["true"])]
        assert check_referenced_files(checks, tmp_path) == set()

    def test_shell_tokenization_degrades_on_bad_quotes(self, tmp_path: Path) -> None:
        # An unbalanced quote makes shlex.split raise -> that check is skipped,
        # never fatal to the guard.
        checks = [Check(name="broken", shell='echo "unbalanced')]
        assert check_referenced_files(checks, tmp_path) == set()

    def test_metric_argv_referenced_script_is_collected(self, tmp_path: Path) -> None:
        (tmp_path / "bench.py").write_text("print(1)\n")
        checks = [
            Check(
                name="perf",
                metric=["python", "bench.py"],
                direction="lower_is_better",
            )
        ]
        assert "bench.py" in check_referenced_files(checks, tmp_path)

    def test_referenced_file_edit_is_a_hit(self, tmp_path: Path) -> None:
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "bench.py").write_text("print(1)\n")
        hits = detect_check_config_edits(
            ["scripts/bench.py"], tmp_path, _empty_snapshot(), {"scripts/bench.py"}
        )
        assert len(hits) == 1
        assert "scripts/bench.py" in hits[0]


class TestSnapshotCheckManifests:
    def test_captures_scripts_and_tool_table(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest"}}))
        (tmp_path / "pyproject.toml").write_text('[tool.ruff]\nselect = ["E"]\n')
        snap = snapshot_check_manifests(tmp_path)
        assert snap["package.json"] == {"test": "vitest"}
        assert snap["pyproject.toml"] == {"ruff": {"select": ["E"]}}

    def test_missing_files_snapshot_as_none(self, tmp_path: Path) -> None:
        assert snapshot_check_manifests(tmp_path) == {
            "package.json": None,
            "pyproject.toml": None,
        }

    def test_unparseable_files_never_raise(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("{not json")
        (tmp_path / "pyproject.toml").write_text("this = = = broken")
        assert snapshot_check_manifests(tmp_path) == {
            "package.json": {},  # read_package_scripts swallows -> no scripts
            "pyproject.toml": None,
        }


# ---------------------------------------------------------------------------
# (b) AssuranceLoop: synthetic failed check + repair, driven by a plain callable.
# ---------------------------------------------------------------------------


def _request(workdir: Path) -> EngineRequest:
    return EngineRequest(directive="# Single-Mandate refactor\nSimplify.", workdir=workdir)


def _always_passing_check() -> list[Check]:
    return [Check(name="smoke", command=["true"])]


def _guard_hit() -> CheckResult:
    return CheckResult(
        name="check-config-integrity",
        passed=False,
        output="- eslint.config.mjs (check config)",
    )


class TestAssuranceLoopCheckConfigGuard:
    def test_guard_hit_drives_a_repair_then_succeeds(self, tmp_path: Path) -> None:
        # attempt 0 "touched" check config; attempt 1 did not.
        per_attempt: list[CheckResult | None] = [_guard_hit(), None]
        calls = {"n": 0}

        def _guard() -> CheckResult | None:
            idx = min(calls["n"], len(per_attempt) - 1)
            calls["n"] += 1
            return per_attempt[idx]

        loop = AssuranceLoop(
            engine=MockEngine(),
            verifier=Verifier(),
            max_repairs=1,
            check_config_guard=_guard,
        )
        report = loop.run(_request(tmp_path), checks=_always_passing_check())

        assert report.success is True
        assert len(report.attempts) == 2
        assert "check-config-integrity" in report.attempts[0].failed_checks
        assert report.attempts[1].failed_checks == []

    def test_repair_addendum_names_the_file_and_the_check(self, tmp_path: Path) -> None:
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
            check_config_guard=_guard_hit,
        )
        loop.run(_request(tmp_path), checks=_always_passing_check())

        assert len(seen_directives) == 2
        assert "eslint.config.mjs" in seen_directives[1]
        assert "check-config-integrity" in seen_directives[1]

    def test_synthetic_result_emits_a_check_finished_event(self, tmp_path: Path) -> None:
        # A synthetic guard has no subprocess so the Verifier never emits an event
        # for it — the loop must, or the law would be enforced invisibly.
        log = tmp_path / "run.jsonl"
        with bind_run_log(log):
            loop = AssuranceLoop(
                engine=MockEngine(),
                verifier=Verifier(),
                max_repairs=0,
                check_config_guard=_guard_hit,
            )
            loop.run(_request(tmp_path), checks=_always_passing_check())

        events = [json.loads(line) for line in log.read_text().splitlines()]
        finished = [
            e
            for e in events
            if e["event"] == "check_finished" and e.get("name") == "check-config-integrity"
        ]
        assert len(finished) == 1
        assert finished[0]["passed"] is False

    def test_no_guard_bound_is_a_no_op(self, tmp_path: Path) -> None:
        loop = AssuranceLoop(engine=MockEngine(), verifier=Verifier(), max_repairs=3)
        report = loop.run(_request(tmp_path), checks=_always_passing_check())

        assert report.success is True
        assert len(report.attempts) == 1
        assert report.attempts[0].failed_checks == []

    def test_quarantining_the_guard_neutralizes_it(self, tmp_path: Path) -> None:
        # A quarantined synthetic still RUNS and is recorded as failed, but never
        # blocks the run nor spends a repair turn.
        loop = AssuranceLoop(
            engine=MockEngine(),
            verifier=Verifier(),
            max_repairs=1,
            check_config_guard=_guard_hit,
            quarantined=["check-config-integrity"],
        )
        report = loop.run(_request(tmp_path), checks=_always_passing_check())

        assert report.success is True
        assert len(report.attempts) == 1
        assert "check-config-integrity" in report.attempts[0].failed_checks


# ---------------------------------------------------------------------------
# (c) runner.py wiring: real git snapshots, opt-out, graceful without git.
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


class TestExecuteMandateCheckConfigIntegration:
    def test_edit_then_revert_fails_then_succeeds(self, tmp_path: Path, monkeypatch) -> None:
        _init_git_repo(tmp_path)

        # attempt 0 silences the lint by editing its own config; attempt 1 reverts
        # that edit and fixes the code instead — the repairable path.
        class _ScriptedEngine:
            name = "mock"

            def __init__(self) -> None:
                self._call_index = 0

            def capabilities(self) -> Capabilities:
                return Capabilities()

            def health_check(self) -> bool:
                return True

            def run(self, request: EngineRequest) -> EngineResult:
                cfg = request.workdir / "eslint.config.mjs"
                if self._call_index == 0:
                    cfg.write_text("export default [{ ignores: ['.claude/**'] }]\n")
                else:
                    cfg.unlink()
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
        assert "check-config-integrity" in report.attempts[0].failed_checks
        assert report.attempts[1].failed_checks == []
        assert report.success is True
        # The edit was reverted by the end -> the final changed set is clean.
        assert report.check_config_edits == []

    def test_edit_never_reverted_fails_the_run_and_surfaces_it(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _init_git_repo(tmp_path)
        engine = _write_files_engine({"eslint.config.mjs": "export default []\n"})
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine())

        bp = Blueprint(
            name="refactor",
            purpose="Simplify.",
            workflow="# w",
            checks=[Check(name="smoke", command=["true"])],
            max_repairs=1,
        )
        report = execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=bp,
            directive="# test\nsimplify",
            engine_override="mock",
            workdir=tmp_path,
        )

        assert report.success is False
        assert report.check_config_edits  # populated
        assert any("eslint.config.mjs" in w for w in report.warnings)

    def test_allow_check_config_permits_the_edit_but_still_surfaces_it(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _init_git_repo(tmp_path)
        engine = _write_files_engine({"eslint.config.mjs": "export default []\n"})
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine())

        bp = Blueprint(
            name="lint-maintenance",
            purpose="Maintain the lint config.",
            workflow="# w",
            checks=[Check(name="smoke", command=["true"])],
            allow_check_config=True,
        )
        report = execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=bp,
            directive="# test\nmaintain",
            engine_override="mock",
            workdir=tmp_path,
        )

        assert report.success is True
        assert all(
            "check-config-integrity" not in a.failed_checks for a in report.attempts
        )
        # Tamper-evidence is always-on even when the guard is waived.
        assert report.check_config_edits
        assert any("allowed by allow_check_config" in w for w in report.warnings)

    def test_outside_git_repo_is_a_silent_no_op(self, tmp_path: Path, monkeypatch) -> None:
        # tmp_path is NOT a git repo — the guard must never raise or block the run.
        engine = _write_files_engine({"eslint.config.mjs": "export default []\n"})
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine())

        bp = Blueprint(
            name="refactor",
            purpose="Simplify.",
            workflow="# w",
            checks=[Check(name="smoke", command=["true"])],
        )
        report = execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=bp,
            directive="# test\nsimplify",
            engine_override="mock",
            workdir=tmp_path,
        )
        assert report.success is True
        assert report.check_config_edits == []


class TestExecuteMandateCheckConfigEvent:
    """The always-on tamper-evidence also surfaces as a `check_config_edited` run
    EVENT, so the event-based run detail sees it — especially the allowed case,
    which fires no synthetic `check-config-integrity` check.
    """

    def test_allowed_run_emits_the_event_with_the_touched_files(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _init_git_repo(tmp_path)
        engine = _write_files_engine({"eslint.config.mjs": "export default []\n"})
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine())

        bp = Blueprint(
            name="lint-maintenance",
            purpose="Maintain the lint config.",
            workflow="# w",
            checks=[Check(name="smoke", command=["true"])],
            allow_check_config=True,
        )
        log = tmp_path / "run.jsonl"
        with bind_run_log(log):
            report = execute_mandate(
                manifest=_MINIMAL_MANIFEST,
                blueprint=bp,
                directive="# test\nmaintain",
                engine_override="mock",
                workdir=tmp_path,
            )

        events = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
        edited = [e for e in events if e["event"] == "check_config_edited"]
        assert len(edited) == 1
        assert edited[0]["files"] == report.check_config_edits
        assert any("eslint.config.mjs" in f for f in edited[0]["files"])

    def test_reverted_edit_emits_no_event(self, tmp_path: Path, monkeypatch) -> None:
        _init_git_repo(tmp_path)

        class _ScriptedEngine:
            name = "mock"

            def __init__(self) -> None:
                self._call_index = 0

            def capabilities(self) -> Capabilities:
                return Capabilities()

            def health_check(self) -> bool:
                return True

            def run(self, request: EngineRequest) -> EngineResult:
                cfg = request.workdir / "eslint.config.mjs"
                if self._call_index == 0:
                    cfg.write_text("export default []\n")
                else:
                    cfg.unlink()
                self._call_index += 1
                return EngineResult(ok=True, output_text="[mock] wrote files")

        engine = _ScriptedEngine()
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine)

        bp = Blueprint(
            name="refactor",
            purpose="Simplify.",
            workflow="# w",
            checks=[Check(name="smoke", command=["true"])],
            max_repairs=1,
        )
        log = tmp_path / "run.jsonl"
        with bind_run_log(log):
            report = execute_mandate(
                manifest=_MINIMAL_MANIFEST,
                blueprint=bp,
                directive="# test\nsimplify",
                engine_override="mock",
                workdir=tmp_path,
            )

        assert report.check_config_edits == []
        events = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
        assert [e for e in events if e["event"] == "check_config_edited"] == []


# ---------------------------------------------------------------------------
# (a) Blueprint.allow_check_config round-trip + RunReport.check_config_edits.
# ---------------------------------------------------------------------------


class TestLoadBlueprintAllowCheckConfig:
    def test_allow_check_config_round_trip(self, tmp_path: Path) -> None:
        blueprints_dir = tmp_path / "blueprints"
        blueprints_dir.mkdir()
        (blueprints_dir / "maint.md").write_text(
            """\
---
name: maint
purpose: Maintain the lint config.
compute_tier: standard
allow_check_config: true
checks:
  - name: smoke
    command: ["true"]
---
# Workflow
Maintain.
"""
        )
        bp = load_blueprint(blueprints_dir, "maint")
        assert bp.allow_check_config is True

    def test_absent_allow_check_config_defaults_false(self, tmp_path: Path) -> None:
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
        assert bp.allow_check_config is False


class TestRunReportCheckConfigEdits:
    def test_defaults_to_empty_list(self) -> None:
        report = RunReport(
            blueprint="x",
            engine="mock",
            success=True,
            attempts=[],
            scorecard=Scorecard(span=0, passes=1, streak=1, touch=0),
            output_text="",
        )
        assert report.check_config_edits == []

    def test_old_report_without_the_field_still_parses(self) -> None:
        # Additive default keeps an archived report (from before this field) loadable.
        data = {
            "blueprint": "x",
            "engine": "mock",
            "success": True,
            "attempts": [],
            "scorecard": {"span": 0, "passes": 1, "streak": 1, "touch": 0},
            "output_text": "",
        }
        report = RunReport.model_validate(data)
        assert report.check_config_edits == []


# ---------------------------------------------------------------------------
# (d) Policy Gate: blueprint-allows-check-config (a standing exception stays visible).
# ---------------------------------------------------------------------------


class TestPolicyAllowsCheckConfig:
    def _bp(self, allow: bool) -> Blueprint:
        return Blueprint(
            name="maint",
            purpose="p",
            workflow="w",
            checks=[Check(name="smoke", command=["true"])],
            allow_check_config=allow,
        )

    def test_allow_true_yields_a_warn_not_an_error(self) -> None:
        violations = lint(_MINIMAL_MANIFEST, [self._bp(True)])
        matching = [v for v in violations if v.rule == "blueprint-allows-check-config"]
        assert len(matching) == 1
        assert matching[0].severity == "warn"
        assert not has_errors(violations)

    def test_allow_false_yields_no_warn(self) -> None:
        violations = lint(_MINIMAL_MANIFEST, [self._bp(False)])
        assert [v for v in violations if v.rule == "blueprint-allows-check-config"] == []
