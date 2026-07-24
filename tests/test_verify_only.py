# test_verify_only.py — Tests for verify-only Flow stages.
# All tests are hermetic (no real model, no network); checks use ["true"] / ["false"]
# so they run on any POSIX system without extra dependencies.
from __future__ import annotations

from pathlib import Path

import pytest

from alc.flow import FlowRunner
from alc.intake import load_manifest


# ---------------------------------------------------------------------------
# Extra Operator Layer fixtures — written into the tmp layer created by
# the shared `operator_layer` fixture from conftest.py.
# ---------------------------------------------------------------------------

_GATE_BLUEPRINT = """\
---
name: gate
purpose: Pure verification gate — checks only, no engine turn.
compute_tier: standard
checks:
  - name: always-pass
    command: ["true"]
---
# Workflow (never executed in verify-only mode)
This body is irrelevant; the stage is verify-only.
"""

_GATE_FAIL_BLUEPRINT = """\
---
name: gate-fail
purpose: Pure verification gate that always fails.
compute_tier: standard
checks:
  - name: always-fail
    command: ["false"]
---
# Workflow (never executed in verify-only mode)
This body is irrelevant; the stage is verify-only.
"""

# Flow: normal mock stage first, then a verify-only stage that passes.
_FLOW_PASS = """\
name: verify-pass-flow
description: Normal engine stage followed by a passing verify-only gate.
stages:
  - name: build
    blueprint: chore
  - name: gate
    blueprint: gate
    verify_only: true
"""

# Flow: failing verify-only stage first, then a normal stage (should never run).
_FLOW_FAIL_FIRST = """\
name: verify-fail-first-flow
description: Failing verify-only gate at the front stops the flow.
stages:
  - name: gate
    blueprint: gate-fail
    verify_only: true
  - name: build
    blueprint: chore
"""

# ---------------------------------------------------------------------------
# require_real_checks fixtures — a gate that resolves to ONLY the scaffold
# smoke placeholder, plus gates that carry a real extra check (pass and fail).
# ---------------------------------------------------------------------------

# Gate whose resolved checks are EXACTLY the scaffold smoke placeholder.
_SMOKE_GATE_BLUEPRINT = """\
---
name: smoke-gate
purpose: Gate that resolves to only the scaffold smoke placeholder.
compute_tier: standard
checks:
  - name: smoke
    command: ["true"]
---
# Workflow (never executed in verify-only mode)
This body is irrelevant; the stage is verify-only.
"""

# Gate with a real check beyond the smoke placeholder — it is NOT smoke-only,
# so require_real_checks is inert and the real checks run (and pass).
_REAL_PASS_GATE_BLUEPRINT = """\
---
name: real-pass-gate
purpose: Gate with a real check beyond the smoke placeholder — passes.
compute_tier: standard
checks:
  - name: smoke
    command: ["true"]
  - name: guard
    command: ["true"]
---
# Workflow (never executed in verify-only mode)
This body is irrelevant; the stage is verify-only.
"""

# Gate with a real check beyond the smoke placeholder — NOT smoke-only, so the
# real checks run and the failing one fails the gate (never inconclusive).
_REAL_FAIL_GATE_BLUEPRINT = """\
---
name: real-fail-gate
purpose: Gate with a real check beyond the smoke placeholder — fails.
compute_tier: standard
checks:
  - name: smoke
    command: ["true"]
  - name: guard
    command: ["false"]
---
# Workflow (never executed in verify-only mode)
This body is irrelevant; the stage is verify-only.
"""

# Flow: engine build stage, then a require_real_checks gate that is smoke-only.
_FLOW_SMOKE_GATE = """\
name: smoke-gate-flow
description: Build stage then a require_real_checks gate that is smoke-only.
stages:
  - name: build
    blueprint: chore
  - name: gate
    blueprint: smoke-gate
    verify_only: true
    require_real_checks: true
"""

# Flow: engine build stage, then a require_real_checks gate whose real checks pass.
_FLOW_REAL_PASS = """\
name: real-pass-gate-flow
description: Build stage then a require_real_checks gate whose real checks pass.
stages:
  - name: build
    blueprint: chore
  - name: gate
    blueprint: real-pass-gate
    verify_only: true
    require_real_checks: true
"""

# Flow: engine build stage, then a require_real_checks gate whose real check fails.
_FLOW_REAL_FAIL = """\
name: real-fail-gate-flow
description: Build stage then a require_real_checks gate whose real check fails.
stages:
  - name: build
    blueprint: chore
  - name: gate
    blueprint: real-fail-gate
    verify_only: true
    require_real_checks: true
"""


@pytest.fixture
def verify_layer(operator_layer: Path) -> Path:
    """Extend the shared operator_layer with verify-only blueprints and flows."""
    blueprints_dir = operator_layer / "blueprints"
    flows_dir = operator_layer / "flows"

    (blueprints_dir / "gate.md").write_text(_GATE_BLUEPRINT)
    (blueprints_dir / "gate-fail.md").write_text(_GATE_FAIL_BLUEPRINT)
    (flows_dir / "verify-pass-flow.yaml").write_text(_FLOW_PASS)
    (flows_dir / "verify-fail-first-flow.yaml").write_text(_FLOW_FAIL_FIRST)

    return operator_layer


@pytest.fixture
def require_real_checks_layer(operator_layer: Path) -> Path:
    """Extend the shared operator_layer with require_real_checks gates and flows."""
    blueprints_dir = operator_layer / "blueprints"
    flows_dir = operator_layer / "flows"

    (blueprints_dir / "smoke-gate.md").write_text(_SMOKE_GATE_BLUEPRINT)
    (blueprints_dir / "real-pass-gate.md").write_text(_REAL_PASS_GATE_BLUEPRINT)
    (blueprints_dir / "real-fail-gate.md").write_text(_REAL_FAIL_GATE_BLUEPRINT)
    (flows_dir / "smoke-gate-flow.yaml").write_text(_FLOW_SMOKE_GATE)
    (flows_dir / "real-pass-gate-flow.yaml").write_text(_FLOW_REAL_PASS)
    (flows_dir / "real-fail-gate-flow.yaml").write_text(_FLOW_REAL_FAIL)

    return operator_layer


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestVerifyOnlyStage:
    def test_passing_verify_only_stage_completes_flow(
        self, verify_layer: Path, tmp_path: Path
    ) -> None:
        """Flow [normal mock stage, verify-only stage with check ["true"]] succeeds.

        Asserts:
        - flow.success is True
        - two stage reports produced
        - stages[1].engine == "(verify-only)"
        - stages[1].attempts == []  (no engine turn)
        """
        from alc.intake import load_flow

        manifest = load_manifest(verify_layer)
        flows_dir = verify_layer.parent / manifest.flows_dir
        flow = load_flow(flows_dir, "verify-pass-flow")

        runner = FlowRunner(manifest=manifest, operator_layer=verify_layer)
        report = runner.run(flow=flow, task="run the gate", workdir=tmp_path)

        assert report.success is True
        assert len(report.stages) == 2

        gate_report = report.stages[1]
        assert gate_report.engine == "(verify-only)"
        assert gate_report.attempts == []
        assert gate_report.success is True

    def test_failing_verify_only_stage_first_stops_flow(
        self, verify_layer: Path, tmp_path: Path
    ) -> None:
        """Verify-only stage with check ["false"] at position 0 triggers fail-fast.

        Asserts:
        - flow.success is False
        - exactly 1 stage report (second stage never ran)
        """
        from alc.intake import load_flow

        manifest = load_manifest(verify_layer)
        flows_dir = verify_layer.parent / manifest.flows_dir
        flow = load_flow(flows_dir, "verify-fail-first-flow")

        runner = FlowRunner(manifest=manifest, operator_layer=verify_layer)
        report = runner.run(flow=flow, task="run the gate", workdir=tmp_path)

        assert report.success is False
        assert len(report.stages) == 1  # fail-fast: second stage skipped

        gate_report = report.stages[0]
        assert gate_report.engine == "(verify-only)"
        assert gate_report.success is False

    def test_verify_only_no_repair_on_failure(
        self, verify_layer: Path, tmp_path: Path
    ) -> None:
        """A failing verify-only stage produces exactly one Verifier pass (no repair).

        Asserts:
        - attempts == []  (no engine turns, no repair loop)
        - success is False (the check failed)
        """
        from alc.intake import load_flow

        manifest = load_manifest(verify_layer)
        flows_dir = verify_layer.parent / manifest.flows_dir
        flow = load_flow(flows_dir, "verify-fail-first-flow")

        runner = FlowRunner(manifest=manifest, operator_layer=verify_layer)
        report = runner.run(flow=flow, task="run the gate", workdir=tmp_path)

        gate_report = report.stages[0]
        assert gate_report.attempts == []
        assert gate_report.success is False
        # The scorecard must show zero passes (no engine turn).
        assert gate_report.scorecard.passes == 0

    def test_passing_gate_does_not_zero_aggregate_streak(
        self, verify_layer: Path, tmp_path: Path
    ) -> None:
        """A passing verify-only gate must not zero the aggregate Flow streak.

        Flow is [one-shot mock engine stage, passing verify-only gate].
        The mock engine produces streak=1; the gate passes so it also produces
        streak=1; therefore the aggregate FlowReport.scorecard.streak must be 1.

        Also verifies that passes sums only the engine stage's passes (gate
        contributes passes=0), so aggregate passes == 1.
        """
        from alc.intake import load_flow

        manifest = load_manifest(verify_layer)
        flows_dir = verify_layer.parent / manifest.flows_dir
        flow = load_flow(flows_dir, "verify-pass-flow")

        runner = FlowRunner(manifest=manifest, operator_layer=verify_layer)
        report = runner.run(flow=flow, task="run the gate", workdir=tmp_path)

        assert report.success is True
        assert report.scorecard.streak == 1, (
            "A passing gate must not zero the aggregate streak"
        )
        # Gate contributes passes=0; the mock engine stage contributes passes=1.
        assert report.scorecard.passes == 1, (
            "Aggregate passes must equal the mock engine stage's passes only"
        )

    def test_failing_gate_keeps_aggregate_streak_zero(
        self, verify_layer: Path, tmp_path: Path
    ) -> None:
        """A failing verify-only gate must keep the aggregate Flow streak at 0.

        The gate fails immediately (fail-fast), so the overall flow is not
        successful and the aggregate streak must be 0.
        """
        from alc.intake import load_flow

        manifest = load_manifest(verify_layer)
        flows_dir = verify_layer.parent / manifest.flows_dir
        flow = load_flow(flows_dir, "verify-fail-first-flow")

        runner = FlowRunner(manifest=manifest, operator_layer=verify_layer)
        report = runner.run(flow=flow, task="run the gate", workdir=tmp_path)

        assert report.success is False
        assert report.scorecard.streak == 0, (
            "A failing gate must keep the aggregate streak at 0"
        )


# ---------------------------------------------------------------------------
# require_real_checks gate: honest INCONCLUSIVE when the project has only the
# placeholder smoke check, inert when the resolved checks are real.
# ---------------------------------------------------------------------------

_GIT_MANIFEST = """\
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

_GIT_CHORE = """\
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


class TestRequireRealChecks:
    def test_require_real_checks_without_verify_only_is_rejected(self) -> None:
        """require_real_checks only gates a verify_only stage: setting it on a
        non-verify_only stage is a pydantic ValidationError at intake."""
        from pydantic import ValidationError

        from alc.models import FlowStage

        with pytest.raises(ValidationError):
            FlowStage(name="g", blueprint="x", require_real_checks=True)

    def test_smoke_only_gate_is_inconclusive_and_names_the_fix(
        self, require_real_checks_layer: Path, tmp_path: Path
    ) -> None:
        """A require_real_checks gate whose resolved checks are ONLY the smoke
        placeholder reports success=False, inconclusive=True, and points the
        operator at how to add real checks."""
        from alc.intake import load_flow

        manifest = load_manifest(require_real_checks_layer)
        flows_dir = require_real_checks_layer.parent / manifest.flows_dir
        flow = load_flow(flows_dir, "smoke-gate-flow")

        runner = FlowRunner(manifest=manifest, operator_layer=require_real_checks_layer)
        report = runner.run(
            flow=flow, task="unship a placeholder-only feature", workdir=tmp_path
        )

        gate = report.stages[-1]
        assert gate.success is False
        assert gate.inconclusive is True
        assert "real checks" in gate.output_text
        assert "alc checks audit" in gate.output_text

    def test_real_checks_run_and_gate_passes_when_they_pass(
        self, require_real_checks_layer: Path, tmp_path: Path
    ) -> None:
        """When the gate resolves REAL checks, require_real_checks is inert: the
        checks actually run and a passing battery passes the gate."""
        from alc.intake import load_flow

        manifest = load_manifest(require_real_checks_layer)
        flows_dir = require_real_checks_layer.parent / manifest.flows_dir
        flow = load_flow(flows_dir, "real-pass-gate-flow")

        runner = FlowRunner(manifest=manifest, operator_layer=require_real_checks_layer)
        report = runner.run(flow=flow, task="unship a real feature", workdir=tmp_path)

        gate = report.stages[-1]
        assert report.success is True
        assert gate.success is True
        assert gate.inconclusive is False
        # The real check actually ran (its result is in the summary).
        assert "guard: pass" in gate.output_text

    def test_real_checks_run_and_gate_fails_when_they_fail(
        self, require_real_checks_layer: Path, tmp_path: Path
    ) -> None:
        """When the gate resolves REAL checks, a failing one fails the gate on
        its own result — never an inconclusive skip."""
        from alc.intake import load_flow

        manifest = load_manifest(require_real_checks_layer)
        flows_dir = require_real_checks_layer.parent / manifest.flows_dir
        flow = load_flow(flows_dir, "real-fail-gate-flow")

        runner = FlowRunner(manifest=manifest, operator_layer=require_real_checks_layer)
        report = runner.run(flow=flow, task="unship a real feature", workdir=tmp_path)

        gate = report.stages[-1]
        assert report.success is False
        assert gate.success is False
        assert gate.inconclusive is False
        # The real check actually ran and failed.
        assert "guard: fail" in gate.output_text

    def test_inconclusive_gate_preserves_work_and_does_not_commit_or_revert(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """A committing flow whose require_real_checks gate is inconclusive is
        neither committed nor reverted: the removal's work stays in the tree."""
        import subprocess

        from alc.engine import Capabilities, EngineResult
        from alc.models import CommitSpec, FlowDefinition, FlowStage

        repo = tmp_path / "repo"
        repo.mkdir()
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
        alc = repo / ".alc"
        (alc / "blueprints").mkdir(parents=True)
        (alc / "flows").mkdir(parents=True)
        (alc / "manifest.yaml").write_text(_GIT_MANIFEST)
        (alc / "blueprints" / "chore.md").write_text(_GIT_CHORE)
        (alc / "blueprints" / "smoke-gate.md").write_text(_SMOKE_GATE_BLUEPRINT)
        subprocess.run(
            ["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "seed operator layer"],
            check=True,
            capture_output=True,
        )

        class _WriteEngine:
            name = "mock"

            def capabilities(self) -> Capabilities:
                return Capabilities()

            def health_check(self) -> bool:
                return True

            def run(self, request):
                # The removal did real work, then the gate finds only placeholder
                # checks — the work ran but cannot be verified.
                (request.workdir / "feature.txt").write_text("real work\n")
                return EngineResult(ok=True, output_text="[mock] removed the feature")

        monkeypatch.setattr(
            "alc.runner.resolve_engine", lambda name, engines: _WriteEngine()
        )

        flow = FlowDefinition(
            name="unship",
            stages=[
                FlowStage(name="remove", blueprint="chore"),
                FlowStage(
                    name="gate",
                    blueprint="smoke-gate",
                    verify_only=True,
                    require_real_checks=True,
                ),
            ],
            commit=CommitSpec(enabled=True, message="feat(auto): {task}"),
        )
        manifest = load_manifest(alc)
        runner = FlowRunner(manifest=manifest, operator_layer=alc)
        report = runner.run(
            flow=flow, task="unship placeholder", engine_override="mock", workdir=repo
        )

        assert report.success is False
        assert report.inconclusive is True
        assert report.commit_sha is None
        # The revert hook must NOT run: the removal's work is preserved.
        assert (repo / "feature.txt").exists()
        # No terminal commit either — only the seed commit exists.
        subjects = subprocess.run(
            ["git", "-C", str(repo), "log", "--format=%s"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        assert subjects == ["seed operator layer"]
