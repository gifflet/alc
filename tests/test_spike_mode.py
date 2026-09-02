# test_spike_mode.py — Hermetic tests for `mode: spike`: the ONE relaxation of the
# checks gate, and the five non-negotiable fences around it:
# (a) Policy Gate rule 1 drops from error to warn, only in this mode;
# (b) the runner forces max_repairs = 0, ignoring any Blueprint-declared budget;
# (c) cmd_run forces isolation and forbids the exit-commit, regardless of --isolate;
# (d) RunReport.spike is True and the run is excluded from the Scorecard streak;
# (e) a spike stage combined with an enabled Flow CommitSpec is a Policy Gate error.
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from alc.cli import cmd_run, cmd_spike
from alc.intake import load_blueprint
from alc.models import Blueprint, Check, CommitSpec, FlowDefinition, FlowStage, Manifest
from alc.policy import has_errors, lint, lint_flow
from alc.runner import execute_mandate

_MINIMAL_MANIFEST = Manifest(
    version=1,
    default_engine="mock",
    compute_tiers={"standard": {"mock": "mock-small"}},
    engines={"mock": {"type": "mock"}},
)


def _spike_bp(**overrides) -> Blueprint:
    defaults: dict = dict(
        name="spike", purpose="Explore fast, throwaway.", workflow="# explore", mode="spike"
    )
    defaults.update(overrides)
    return Blueprint(**defaults)


# ---------------------------------------------------------------------------
# Front-matter round-trip
# ---------------------------------------------------------------------------


class TestLoadBlueprintMode:
    def test_mode_spike_round_trip(self, tmp_path: Path) -> None:
        blueprints_dir = tmp_path / "blueprints"
        blueprints_dir.mkdir()
        (blueprints_dir / "spike.md").write_text(
            """\
---
name: spike
purpose: Explore fast.
compute_tier: standard
mode: spike
---
# Workflow
Explore.
"""
        )
        bp = load_blueprint(blueprints_dir, "spike")
        assert bp.mode == "spike"

    def test_absent_mode_is_none(self, tmp_path: Path) -> None:
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
        assert bp.mode is None


class TestBlueprintModeValidation:
    def test_unrecognised_mode_value_raises(self) -> None:
        with pytest.raises(ValidationError):
            Blueprint(name="x", purpose="p", workflow="w", mode="yolo")


# ---------------------------------------------------------------------------
# (a) Policy Gate rule 1: blueprint_has_checks drops to warn only in spike mode
# ---------------------------------------------------------------------------


class TestPolicyRule1SpikeDowngrade:
    def test_no_checks_and_no_mode_is_error(self) -> None:
        bp = Blueprint(name="x", purpose="p", workflow="w")
        violations = lint(_MINIMAL_MANIFEST, [bp])
        matching = [v for v in violations if v.rule == "blueprint_has_checks"]
        assert len(matching) == 1
        assert matching[0].severity == "error"
        assert has_errors(violations)

    def test_no_checks_with_mode_spike_is_warn(self) -> None:
        bp = _spike_bp()
        violations = lint(_MINIMAL_MANIFEST, [bp])
        matching = [v for v in violations if v.rule == "blueprint_has_checks"]
        assert len(matching) == 1
        assert matching[0].severity == "warn"
        assert not has_errors(violations)

    def test_mode_spike_with_checks_raises_no_rule1_violation(self) -> None:
        bp = _spike_bp(checks=[Check(name="smoke", command=["true"])])
        violations = lint(_MINIMAL_MANIFEST, [bp])
        assert [v for v in violations if v.rule == "blueprint_has_checks"] == []


# ---------------------------------------------------------------------------
# (b) The runner forces max_repairs = 0 in spike mode
# ---------------------------------------------------------------------------


class TestRunnerForcesMaxRepairsZero:
    def test_spike_forces_one_attempt_even_when_checks_never_pass(
        self, tmp_path: Path
    ) -> None:
        bp = _spike_bp(checks=[Check(name="always-fail", command=["false"])])
        report = execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=bp,
            directive="# test\ndo it",
            engine_override="mock",
            workdir=tmp_path,
        )
        assert len(report.attempts) == 1

    def test_spike_overrides_a_blueprint_declared_max_repairs(
        self, tmp_path: Path
    ) -> None:
        bp = _spike_bp(
            max_repairs=5, checks=[Check(name="always-fail", command=["false"])]
        )
        report = execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=bp,
            directive="# test\ndo it",
            engine_override="mock",
            workdir=tmp_path,
        )
        assert len(report.attempts) == 1

    def test_non_spike_blueprint_keeps_its_own_budget(self, tmp_path: Path) -> None:
        bp = Blueprint(
            name="x",
            purpose="p",
            workflow="w",
            max_repairs=2,
            checks=[Check(name="always-fail", command=["false"])],
        )
        report = execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=bp,
            directive="# test\ndo it",
            engine_override="mock",
            workdir=tmp_path,
        )
        assert len(report.attempts) == 3  # 1 initial + 2 repairs


# ---------------------------------------------------------------------------
# (d) RunReport.spike + Scorecard streak exclusion
# ---------------------------------------------------------------------------


class TestRunReportSpikeField:
    def test_spike_true_for_spike_mode(self, tmp_path: Path) -> None:
        report = execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=_spike_bp(),
            directive="# test\ndo it",
            engine_override="mock",
            workdir=tmp_path,
        )
        assert report.spike is True

    def test_spike_false_for_a_normal_blueprint(self, tmp_path: Path) -> None:
        bp = Blueprint(
            name="x", purpose="p", workflow="w", checks=[Check(name="smoke", command=["true"])]
        )
        report = execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=bp,
            directive="# test\ndo it",
            engine_override="mock",
            workdir=tmp_path,
        )
        assert report.spike is False


class TestSpikeExcludedFromStreak:
    def test_one_shot_spike_success_has_streak_zero(self, tmp_path: Path) -> None:
        # Passing checks one-shot would normally score streak=1; spike mode must
        # force it to 0 so it never inflates the Scorecard's streak.
        bp = _spike_bp(checks=[Check(name="smoke", command=["true"])])
        report = execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=bp,
            directive="# test\ndo it",
            engine_override="mock",
            workdir=tmp_path,
        )
        assert report.success is True
        assert report.scorecard.streak == 0

    def test_non_spike_one_shot_still_gets_streak_one(self, tmp_path: Path) -> None:
        bp = Blueprint(
            name="x", purpose="p", workflow="w", checks=[Check(name="smoke", command=["true"])]
        )
        report = execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=bp,
            directive="# test\ndo it",
            engine_override="mock",
            workdir=tmp_path,
        )
        assert report.scorecard.streak == 1


# ---------------------------------------------------------------------------
# (c) cmd_run forces isolation and forbids the exit-commit for a spike Blueprint
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
"""

_SPIKE_BLUEPRINT_MD = """\
---
name: spike
purpose: Explore fast, throwaway.
compute_tier: standard
mode: spike
---
# Workflow
Explore the idea.
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


def _build_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    alc = repo / ".alc"
    (alc / "blueprints").mkdir(parents=True)
    (alc / "manifest.yaml").write_text(_MANIFEST_YAML)
    (alc / "blueprints" / "spike.md").write_text(_SPIKE_BLUEPRINT_MD)
    _commit_all(repo, "seed operator layer")
    return repo


def _write_files_engine(files: dict[str, str]):
    """Return a MockEngine-like class writing each rel_path->content into the
    request workdir on every turn."""
    from alc.engine import Capabilities, EngineResult

    class _WriteFilesEngine:
        name = "mock"

        def capabilities(self) -> Capabilities:
            return Capabilities()

        def health_check(self) -> bool:
            return True

        def run(self, request):
            for rel_path, content in files.items():
                dst = request.workdir / rel_path
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(content)
            return EngineResult(ok=True, output_text="[mock] wrote files")

    return _WriteFilesEngine


def _run_ns(**overrides) -> argparse.Namespace:
    defaults = {
        "blueprint": "spike",
        "task": "try a risky idea",
        "engine": "mock",
        "isolate": False,  # deliberately NOT requested — spike must force it anyway
        "primer": None,
        "bundle": False,
        "from_bundle": None,
        "tier": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _list_branches(repo: Path, pattern: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), "branch", "--list", pattern],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.lstrip("* ").strip() for line in result.stdout.splitlines() if line.strip()]


class TestCmdRunForcesIsolationForSpike:
    def test_spike_runs_isolated_even_without_the_isolate_flag(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        repo = _build_repo(tmp_path)
        engine = _write_files_engine({"spike_notes.txt": "learned something\n"})
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine())
        monkeypatch.chdir(repo)

        exit_code = cmd_run(_run_ns(isolate=False))

        assert exit_code == 0
        # The agent's write never landed in the shared working tree.
        assert not (repo / "spike_notes.txt").exists()

    def test_spike_never_commits_even_on_success(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        repo = _build_repo(tmp_path)
        engine = _write_files_engine({"spike_notes.txt": "learned something\n"})
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine())
        monkeypatch.chdir(repo)

        exit_code = cmd_run(_run_ns(isolate=False))

        assert exit_code == 0
        out = capsys.readouterr().out
        assert "No changes were made; nothing to isolate." in out
        assert _list_branches(repo, "alc/run-*") == []

    def test_non_spike_blueprint_is_unaffected(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """Byte-identity: a plain --isolate run still commits as before."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        alc = repo / ".alc"
        (alc / "blueprints").mkdir(parents=True)
        (alc / "manifest.yaml").write_text(_MANIFEST_YAML)
        (alc / "blueprints" / "chore.md").write_text(
            """\
---
name: chore
purpose: Apply a low-risk change.
compute_tier: standard
checks:
  - name: smoke
    command: ["true"]
---
# Workflow
1. Make the smallest change that satisfies the task.
"""
        )
        _commit_all(repo, "seed operator layer")

        engine = _write_files_engine({"feature.txt": "the feature\n"})
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine())
        monkeypatch.chdir(repo)

        exit_code = cmd_run(_run_ns(blueprint="chore", isolate=True))

        assert exit_code == 0
        assert "Isolated changes committed on branch" in capsys.readouterr().out
        assert _list_branches(repo, "alc/run-*") != []


class TestCmdRunArchivesRunReport:
    """A direct `alc run` archives its RunReport as a FlowReport `*.report.json` in
    runs/, so `alc audit` + Mix Health (which aggregate FlowReports) count interactive
    runs — a spike, being throwaway, is never archived."""

    def _chore_repo(self, tmp_path: Path) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        alc = repo / ".alc"
        (alc / "blueprints").mkdir(parents=True)
        (alc / "manifest.yaml").write_text(_MANIFEST_YAML)
        (alc / "blueprints" / "chore.md").write_text(
            "---\nname: chore\npurpose: Apply a low-risk change.\n"
            "compute_tier: standard\narchetype: builder\nchecks:\n"
            '  - name: smoke\n    command: ["true"]\n---\n# Workflow\n1. Make the change.\n'
        )
        _commit_all(repo, "seed operator layer")
        return repo

    def test_non_spike_run_archives_a_flowreport_with_the_archetype(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        import json

        repo = self._chore_repo(tmp_path)
        engine = _write_files_engine({"feature.txt": "the feature\n"})
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine())
        monkeypatch.chdir(repo)

        assert cmd_run(_run_ns(blueprint="chore", isolate=True)) == 0

        reports = list((repo / ".alc" / "runs").glob("*.report.json"))
        assert len(reports) == 1, reports
        # An ISOLATED run names the report after its branch (alc/run-<hex> ->
        # alc-run-<hex>.report.json) so `alc discard` can delete it on discard.
        assert reports[0].name.startswith("alc-run-")
        data = json.loads(reports[0].read_text())
        assert data["success"] is True
        assert data["flow"] == "chore"
        # The stage carries Blueprint.archetype, so Mix Health buckets it correctly.
        assert data["stages"][0]["archetype"] == "builder"

    def test_spike_run_is_never_archived(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        repo = _build_repo(tmp_path)  # ships the spike blueprint
        engine = _write_files_engine({"spike_notes.txt": "learned\n"})
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine())
        monkeypatch.chdir(repo)

        assert cmd_run(_run_ns(blueprint="spike", isolate=False)) == 0

        assert list((repo / ".alc" / "runs").glob("*.report.json")) == []


# ---------------------------------------------------------------------------
# T2: `alc spike "<task>"` sugar over cmd_run
# ---------------------------------------------------------------------------


class TestCmdSpikeSugar:
    def test_runs_the_spike_blueprint_isolated_and_uncommitted(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        repo = _build_repo(tmp_path)
        engine = _write_files_engine({"notes.txt": "x\n"})
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine())
        monkeypatch.chdir(repo)

        # json=True: the spike fence is asserted below, and the report is the
        # only place it is stated — a spike is never archived, so there is no
        # file to read it from afterwards.
        exit_code = cmd_spike(
            argparse.Namespace(task="try a risky idea", engine="mock", json=True)
        )

        assert exit_code == 0
        out = capsys.readouterr().out
        assert '"blueprint": "spike"' in out
        assert '"spike": true' in out  # the fenced relaxation is recorded
        assert not (repo / "notes.txt").exists()  # isolated + discarded, never landed


# ---------------------------------------------------------------------------
# (e) Policy Gate: mode: spike + an enabled Flow CommitSpec is an error
# ---------------------------------------------------------------------------


class TestPolicySpikeForbidsCommit:
    def _spike_blueprint(self) -> Blueprint:
        return Blueprint(name="spike", purpose="explore", workflow="# w", mode="spike")

    def _chore_blueprint(self) -> Blueprint:
        return Blueprint(
            name="chore", purpose="p", workflow="w", checks=[Check(name="smoke", command=["true"])]
        )

    def test_spike_stage_with_enabled_commit_is_error(self) -> None:
        flow = FlowDefinition(
            name="risky",
            stages=[FlowStage(name="try", blueprint="spike")],
            commit=CommitSpec(enabled=True),
        )
        violations = lint_flow(
            flow, {"spike"}, stage_blueprints={"try": self._spike_blueprint()}
        )
        matching = [v for v in violations if v.rule == "flow-spike-forbids-commit"]
        assert len(matching) == 1
        assert matching[0].severity == "error"
        assert has_errors(violations)

    def test_spike_stage_with_disabled_commit_is_fine(self) -> None:
        flow = FlowDefinition(
            name="risky",
            stages=[FlowStage(name="try", blueprint="spike")],
            commit=CommitSpec(enabled=False),
        )
        violations = lint_flow(
            flow, {"spike"}, stage_blueprints={"try": self._spike_blueprint()}
        )
        assert [v for v in violations if v.rule == "flow-spike-forbids-commit"] == []

    def test_spike_stage_with_no_commit_block_is_fine(self) -> None:
        flow = FlowDefinition(name="risky", stages=[FlowStage(name="try", blueprint="spike")])
        violations = lint_flow(
            flow, {"spike"}, stage_blueprints={"try": self._spike_blueprint()}
        )
        assert violations == []

    def test_non_spike_stage_with_enabled_commit_is_fine(self) -> None:
        flow = FlowDefinition(
            name="ship",
            stages=[FlowStage(name="do", blueprint="chore")],
            commit=CommitSpec(enabled=True),
        )
        violations = lint_flow(
            flow, {"chore"}, stage_blueprints={"do": self._chore_blueprint()}
        )
        assert [v for v in violations if v.rule == "flow-spike-forbids-commit"] == []

    def test_omitting_stage_blueprints_skips_the_check(self) -> None:
        """Backward compatible: existing callers that don't pass stage_blueprints
        never trip the new rule (byte-identical to before rule 4 existed)."""
        flow = FlowDefinition(
            name="risky",
            stages=[FlowStage(name="try", blueprint="spike")],
            commit=CommitSpec(enabled=True),
        )
        violations = lint_flow(flow, {"spike"})
        assert [v for v in violations if v.rule == "flow-spike-forbids-commit"] == []


class TestFlowRunnerBlocksSpikeCommitCombo:
    def test_flow_runner_raises_policy_violation(self, tmp_path: Path) -> None:
        from alc.flow import FlowRunner
        from alc.intake import load_flow, load_manifest
        from alc.runner import PolicyViolationError

        alc = tmp_path / ".alc"
        (alc / "blueprints").mkdir(parents=True)
        (alc / "flows").mkdir(parents=True)
        (alc / "manifest.yaml").write_text(_MANIFEST_YAML)
        (alc / "blueprints" / "spike.md").write_text(_SPIKE_BLUEPRINT_MD)
        (alc / "flows" / "risky.yaml").write_text(
            "name: risky\n"
            "stages:\n"
            "  - name: try\n"
            "    blueprint: spike\n"
            "commit:\n"
            "  enabled: true\n"
        )
        manifest = load_manifest(alc)
        flow = load_flow(alc / "flows", "risky")
        runner = FlowRunner(manifest=manifest, operator_layer=alc)

        with pytest.raises(PolicyViolationError, match="mode: spike"):
            runner.run(flow=flow, task="try something risky", workdir=tmp_path)


def test_spike_is_marked_on_the_mandate_started_event(tmp_path: Path) -> None:
    """A reader of the run log must be able to tell a spike from a real demand.

    The spike's checks gate is deliberately relaxed. Without this flag on the
    event, a spike's verdict reads exactly like a verified change's — selling a
    guarantee the run never made.
    """
    import json

    from alc.events import bind_run_log

    log = tmp_path / "run.jsonl"
    with bind_run_log(log):
        execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=_spike_bp(),
            directive="# test\ndo it",
            engine_override="mock",
            workdir=tmp_path,
        )

    started = [
        json.loads(line)
        for line in log.read_text().splitlines()
        if json.loads(line)["event"] == "mandate_started"
    ]
    assert started, "the spike emitted no mandate_started"
    assert started[0]["spike"] is True
