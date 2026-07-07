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
