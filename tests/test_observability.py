# test_observability.py — Hermetic tests for Finding 1 & 2 observability improvements.
#
# Finding 1: queue and flow print a ▶ announcement header to stderr before running.
# Finding 2: cmd_tick prints _failure_reason output after FAILED summary lines.
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from alc.cli import _failure_reason
from alc.flow import FlowRunner
from alc.intake import load_flow, load_manifest
from alc.models import (
    FlowReport,
    RunReport,
    Scorecard,
    TickResult,
)
from alc.queue import process_queue


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TASK_YAML = """\
flow: ship
task: "tidy"
engine: mock
isolate: false
"""

_VERIFY_FLOW = """\
name: verify-ship
description: A two-stage flow where stage 2 is verify-only.
stages:
  - name: build
    blueprint: chore
  - name: gate
    blueprint: chore
    verify_only: true
"""


def _make_run_report(output_text: str, success: bool = False) -> RunReport:
    """Build a minimal RunReport for unit tests."""
    return RunReport(
        blueprint="chore",
        engine="mock",
        success=success,
        attempts=[],
        scorecard=Scorecard(span=0, passes=0, streak=0, touch=0),
        output_text=output_text,
    )


def _make_tick_result(
    task_file: str,
    output_text: str,
    success: bool = False,
) -> TickResult:
    """Build a TickResult wrapping a FlowReport with one stage."""
    run = _make_run_report(output_text, success=success)
    flow_report = FlowReport(
        flow="ship",
        engine="mock",
        success=success,
        stages=[run],
        scorecard=run.scorecard,
    )
    return TickResult(
        task_file=task_file,
        flow="ship",
        success=success,
        report=flow_report,
    )


# ---------------------------------------------------------------------------
# Finding 1a — queue._process_task prints a ▶ header to stderr
# ---------------------------------------------------------------------------


class TestQueueHeader:
    def test_header_printed_to_stderr(
        self, operator_layer: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """▶ header with task filename and kind:unit appears on stderr before run."""
        manifest = load_manifest(operator_layer)

        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "myjob.yaml").write_text(_TASK_YAML)

        process_queue(manifest, operator_layer)

        captured = capsys.readouterr()
        # There must be at least one line starting with ▶ on stderr.
        header_lines = [ln for ln in captured.err.splitlines() if ln.startswith("▶ ")]
        assert header_lines, "No ▶ header line found on stderr"

        # The header must contain the task filename and kind:unit.
        header = header_lines[0]
        assert "myjob.yaml" in header
        assert "flow:ship" in header

    def test_header_contains_kind_and_unit_for_specialist(
        self, operator_layer: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """A specialist queue task emits a ▶ header with kind=specialist."""
        manifest = load_manifest(operator_layer)

        # Write the specialist definition.
        specialists_dir = operator_layer / "specialists"
        specialists_dir.mkdir(exist_ok=True)
        (specialists_dir / "db.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": "db",
                    "area": "database layer",
                    "blueprint": "chore",
                    "knowledge_path": ".alc/specialists/db.knowledge.md",
                }
            )
        )

        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "spec.yaml").write_text(
            "kind: specialist\nname: db\ntask: document\nengine: mock\nisolate: false\n"
        )

        process_queue(manifest, operator_layer)

        captured = capsys.readouterr()
        header_lines = [ln for ln in captured.err.splitlines() if ln.startswith("▶ ")]
        assert header_lines, "No ▶ header line found on stderr"
        header = header_lines[0]
        assert "spec.yaml" in header
        assert "specialist:db" in header


# ---------------------------------------------------------------------------
# Finding 1b — FlowRunner.run prints a ▶ stage header for each stage
# ---------------------------------------------------------------------------


class TestFlowHeader:
    def test_one_header_per_stage(
        self, operator_layer: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """FlowRunner.run prints one ▶ stage header per stage to stderr."""
        manifest = load_manifest(operator_layer)
        flows_dir = operator_layer.parent / manifest.flows_dir
        flow = load_flow(flows_dir, "ship")  # 2-stage: plan + build

        runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)
        runner.run(flow=flow, task="test task", engine_override="mock")

        captured = capsys.readouterr()
        stage_headers = [
            ln for ln in captured.err.splitlines() if ln.startswith("▶ stage ")
        ]
        assert len(stage_headers) == 2, f"Expected 2 stage headers, got: {stage_headers}"

    def test_verify_only_stage_header_ends_with_suffix(
        self, operator_layer: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """A verify_only stage's header ends with '(verify-only)'."""
        manifest = load_manifest(operator_layer)

        # Write the 2-stage flow with a verify_only second stage.
        flows_dir = operator_layer.parent / manifest.flows_dir
        (flows_dir / "verify-ship.yaml").write_text(_VERIFY_FLOW)
        flow = load_flow(flows_dir, "verify-ship")

        runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)
        runner.run(flow=flow, task="test task", engine_override="mock")

        captured = capsys.readouterr()
        stage_headers = [
            ln for ln in captured.err.splitlines() if ln.startswith("▶ stage ")
        ]
        assert len(stage_headers) == 2, f"Expected 2 stage headers, got: {stage_headers}"

        # Only the verify_only stage should carry the suffix.
        verify_headers = [h for h in stage_headers if h.endswith("(verify-only)")]
        assert len(verify_headers) == 1, f"Expected 1 verify-only header, got: {verify_headers}"

        normal_headers = [h for h in stage_headers if not h.endswith("(verify-only)")]
        assert len(normal_headers) == 1

    def test_header_contains_stage_name_and_blueprint(
        self, operator_layer: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Each stage header includes the stage name and blueprint name."""
        manifest = load_manifest(operator_layer)
        flows_dir = operator_layer.parent / manifest.flows_dir
        flow = load_flow(flows_dir, "ship")

        runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)
        runner.run(flow=flow, task="test task", engine_override="mock")

        captured = capsys.readouterr()
        stage_headers = [
            ln for ln in captured.err.splitlines() if ln.startswith("▶ stage ")
        ]
        # ship flow: stage "plan" blueprint "plan", stage "build" blueprint "chore".
        assert any("plan" in h and "blueprint:plan" in h for h in stage_headers)
        assert any("build" in h and "blueprint:chore" in h for h in stage_headers)


# ---------------------------------------------------------------------------
# Finding 2 — _failure_reason unit tests (no I/O)
# ---------------------------------------------------------------------------


class TestFailureReason:
    def test_long_output_truncated_to_400_chars_with_ellipsis(
        self, tmp_path: Path
    ) -> None:
        """output_text > 400 chars: result contains last 400 chars and leading '…'."""
        long_text = "x" * 300 + "y" * 200  # 500 chars total; last 400 = 100 x's + 200 y's
        result = _make_tick_result("job1.yaml", long_text)

        reason = _failure_reason(result, tmp_path)

        # The leading ellipsis must appear (because 500 > 400).
        assert "…" in reason

        # The last 400 characters of the original text are included in reason.
        # The tail is a single line (no newlines in long_text), so the first
        # content line is "    …<tail>" — check that tail chars appear after '…'.
        tail = long_text[-400:]
        assert tail in reason

        # The pointer line must reference the correct stem.
        assert f"    see: {tmp_path}/done/job1.report.json" in reason

    def test_exact_400_chars_no_ellipsis(self, tmp_path: Path) -> None:
        """output_text == 400 chars: no ellipsis prepended."""
        text = "a" * 400
        result = _make_tick_result("job2.yaml", text)

        reason = _failure_reason(result, tmp_path)

        # Exactly 400 chars — no truncation needed.
        assert "…" not in reason
        assert "    " + "a" * 400 in reason

    def test_empty_output_text_returns_only_pointer(self, tmp_path: Path) -> None:
        """When the last stage's output_text is empty, only the pointer line is returned."""
        result = _make_tick_result("empty.yaml", "")

        reason = _failure_reason(result, tmp_path)

        assert reason == f"    see: {tmp_path}/done/empty.report.json"

    def test_no_stages_returns_only_pointer(self, tmp_path: Path) -> None:
        """When FlowReport.stages is empty, only the pointer line is returned."""
        flow_report = FlowReport(
            flow="ship",
            engine="mock",
            success=False,
            stages=[],
            scorecard=Scorecard(span=0, passes=0, streak=0, touch=0),
        )
        result = TickResult(
            task_file="nostages.yaml",
            flow="ship",
            success=False,
            report=flow_report,
        )

        reason = _failure_reason(result, tmp_path)

        assert reason == f"    see: {tmp_path}/done/nostages.report.json"

    def test_pointer_uses_task_file_stem_not_full_name(self, tmp_path: Path) -> None:
        """The pointer path is built from the task_file stem (without .yaml)."""
        result = _make_tick_result("my-task-001.yaml", "some output")

        reason = _failure_reason(result, tmp_path)

        # Stem is "my-task-001", not "my-task-001.yaml".
        assert "my-task-001.report.json" in reason
        assert "my-task-001.yaml.report.json" not in reason

    def test_pointer_uses_queue_dir_in_path(self, tmp_path: Path) -> None:
        """The pointer includes queue_dir as the base of the done/ path."""
        queue_dir = tmp_path / ".alc" / "queue"
        result = _make_tick_result("t1.yaml", "")

        reason = _failure_reason(result, queue_dir)

        assert str(queue_dir) in reason
        assert f"{queue_dir}/done/t1.report.json" in reason

    def test_indentation_four_spaces_per_line(self, tmp_path: Path) -> None:
        """Every line of the tail output is indented by exactly 4 spaces."""
        multiline = "line one\nline two\nline three"
        result = _make_tick_result("multi.yaml", multiline)

        reason = _failure_reason(result, tmp_path)

        lines = reason.splitlines()
        # Exclude the pointer line (last line).
        content_lines = lines[:-1]
        for ln in content_lines:
            assert ln.startswith("    "), f"Line not indented 4 spaces: {ln!r}"
