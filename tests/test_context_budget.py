# test_context_budget.py — Tests for Context Budget automation: Primer + bundle.
# All tests are hermetic (no real model, no network).
from __future__ import annotations

from pathlib import Path

import pytest

from alc.bundle import summarize_bundle, write_bundle
from alc.flow import _compose_stage_directive
from alc.intake import load_blueprint, load_manifest
from alc.models import AttemptRecord, Blueprint, Check, FlowReport, ReportSpec, RunReport, Scorecard
from alc.primer import load_primer
from alc.runner import MandateRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scorecard() -> Scorecard:
    return Scorecard(span=1, passes=1, streak=1, touch=0)


def _run_report(output_text: str = "DID THE THING", success: bool = True) -> RunReport:
    return RunReport(
        blueprint="chore",
        engine="mock",
        success=success,
        attempts=[AttemptRecord(index=0, engine_ok=True, failed_checks=[])],
        scorecard=_scorecard(),
        output_text=output_text,
    )


def _flow_report(stage_output: str = "STAGE OUT", success: bool = True) -> FlowReport:
    stage = RunReport(
        blueprint="chore",
        engine="mock",
        success=success,
        attempts=[AttemptRecord(index=0, engine_ok=True, failed_checks=[])],
        scorecard=_scorecard(),
        output_text=stage_output,
    )
    return FlowReport(
        flow="ship",
        engine="mock",
        success=success,
        stages=[stage],
        scorecard=_scorecard(),
    )


def _minimal_blueprint() -> Blueprint:
    return Blueprint(
        name="chore",
        purpose="Apply a low-risk maintenance change.",
        compute_tier="standard",
        checks=[Check(name="smoke", command=["true"])],
        report=ReportSpec(format="json", schema={}),
        workflow="## Workflow\n\n1. Do the thing.",
    )


# ---------------------------------------------------------------------------
# Primer tests
# ---------------------------------------------------------------------------


class TestLoadPrimer:
    def test_load_primer_reads_file(self, tmp_path: Path) -> None:
        primers_dir = tmp_path / "primers"
        primers_dir.mkdir()
        (primers_dir / "overview.md").write_text("# Overview\nSome curated context.")

        result = load_primer(primers_dir, "overview")

        assert "Overview" in result
        assert "curated context" in result

    def test_load_primer_missing_raises(self, tmp_path: Path) -> None:
        primers_dir = tmp_path / "primers"
        primers_dir.mkdir()

        with pytest.raises(FileNotFoundError, match="does-not-exist"):
            load_primer(primers_dir, "does-not-exist")


# ---------------------------------------------------------------------------
# _compose_directive injection tests (MandateRunner)
# ---------------------------------------------------------------------------


class TestComposeDirectiveInjectsPrimedContext:
    def test_injects_primed_context_when_truthy(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        blueprints_dir = operator_layer.parent / manifest.blueprints_dir
        blueprint = load_blueprint(blueprints_dir, "chore")

        runner = MandateRunner(manifest, operator_layer)
        result = runner._compose_directive(blueprint, "tidy", extra_context="ZZZ-PRIMED")

        assert "ZZZ-PRIMED" in result
        assert "## Primed context" in result

    def test_omits_primed_section_when_none(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        blueprints_dir = operator_layer.parent / manifest.blueprints_dir
        blueprint = load_blueprint(blueprints_dir, "chore")

        runner = MandateRunner(manifest, operator_layer)
        result = runner._compose_directive(blueprint, "tidy", extra_context=None)

        assert "## Primed context" not in result

    def test_workflow_always_present(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        blueprints_dir = operator_layer.parent / manifest.blueprints_dir
        blueprint = load_blueprint(blueprints_dir, "chore")

        runner = MandateRunner(manifest, operator_layer)
        result = runner._compose_directive(blueprint, "tidy", extra_context="CTX")

        assert blueprint.workflow in result

    def test_primed_section_appears_before_workflow(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        blueprints_dir = operator_layer.parent / manifest.blueprints_dir
        blueprint = load_blueprint(blueprints_dir, "chore")

        runner = MandateRunner(manifest, operator_layer)
        result = runner._compose_directive(blueprint, "tidy", extra_context="ZZZ-PRIMED")

        primed_pos = result.index("ZZZ-PRIMED")
        workflow_pos = result.index(blueprint.workflow)
        assert primed_pos < workflow_pos


# ---------------------------------------------------------------------------
# _compose_stage_directive injection tests (FlowRunner)
# ---------------------------------------------------------------------------


class TestComposeStageDirectiveInjectsPrimedContext:
    def test_injects_primed_context_when_truthy(self) -> None:
        blueprint = _minimal_blueprint()

        result = _compose_stage_directive(
            flow_name="ship",
            stage_name="build",
            blueprint=blueprint,
            task="tidy",
            upstream_outputs=[],
            extra_context="ZZZ-PRIMED",
        )

        assert "ZZZ-PRIMED" in result
        assert "## Primed context" in result

    def test_omits_primed_section_when_none(self) -> None:
        blueprint = _minimal_blueprint()

        result = _compose_stage_directive(
            flow_name="ship",
            stage_name="build",
            blueprint=blueprint,
            task="tidy",
            upstream_outputs=[],
            extra_context=None,
        )

        assert "## Primed context" not in result

    def test_primed_section_appears_before_upstream_and_workflow(self) -> None:
        blueprint = _minimal_blueprint()

        result = _compose_stage_directive(
            flow_name="ship",
            stage_name="build",
            blueprint=blueprint,
            task="tidy",
            upstream_outputs=["## plan output\nSOME PLAN"],
            extra_context="ZZZ-PRIMED",
        )

        primed_pos = result.index("ZZZ-PRIMED")
        upstream_pos = result.index("SOME PLAN")
        workflow_pos = result.index(blueprint.workflow)
        assert primed_pos < upstream_pos < workflow_pos


# ---------------------------------------------------------------------------
# Bundle write + summarize tests
# ---------------------------------------------------------------------------


class TestWriteAndSummarizeBundleRunReport:
    def test_write_bundle_creates_jsonl_file(self, tmp_path: Path) -> None:
        bundles_dir = tmp_path / "bundles"
        report = _run_report()

        path = write_bundle(bundles_dir, "chore", "tidy", report)

        assert path.exists()
        assert path.suffix == ".jsonl"
        assert path.parent == bundles_dir

    def test_summarize_bundle_contains_task_and_output(self, tmp_path: Path) -> None:
        bundles_dir = tmp_path / "bundles"
        report = _run_report(output_text="DID THE THING")

        path = write_bundle(bundles_dir, "chore", "tidy", report)
        summary = summarize_bundle(path)

        assert "tidy" in summary
        assert "DID THE THING" in summary

    def test_summarize_bundle_reflects_success_state(self, tmp_path: Path) -> None:
        bundles_dir = tmp_path / "bundles"
        report = _run_report(success=True)

        path = write_bundle(bundles_dir, "chore", "tidy", report)
        summary = summarize_bundle(path)

        assert "True" in summary

    def test_summarize_bundle_includes_attempt_count(self, tmp_path: Path) -> None:
        bundles_dir = tmp_path / "bundles"
        report = _run_report()

        path = write_bundle(bundles_dir, "chore", "tidy", report)
        summary = summarize_bundle(path)

        # One AttemptRecord in the fixture.
        assert "Attempts: 1" in summary

    def test_bundle_file_stem_is_8_hex_chars(self, tmp_path: Path) -> None:
        bundles_dir = tmp_path / "bundles"
        report = _run_report()

        path = write_bundle(bundles_dir, "chore", "tidy", report)
        stem = path.stem
        assert len(stem) == 8
        assert all(c in "0123456789abcdef" for c in stem)


class TestWriteBundleFlowReport:
    def test_write_bundle_creates_jsonl_for_flow_report(self, tmp_path: Path) -> None:
        bundles_dir = tmp_path / "bundles"
        report = _flow_report()

        path = write_bundle(bundles_dir, "ship", "build the feature", report)

        assert path.exists()
        assert path.suffix == ".jsonl"

    def test_summarize_bundle_mentions_stage_output(self, tmp_path: Path) -> None:
        bundles_dir = tmp_path / "bundles"
        report = _flow_report(stage_output="STAGE OUT TEXT")

        path = write_bundle(bundles_dir, "ship", "build the feature", report)
        summary = summarize_bundle(path)

        assert "STAGE OUT TEXT" in summary

    def test_summarize_bundle_includes_stage_count(self, tmp_path: Path) -> None:
        bundles_dir = tmp_path / "bundles"
        report = _flow_report()

        path = write_bundle(bundles_dir, "ship", "build the feature", report)
        summary = summarize_bundle(path)

        # One stage in the fixture.
        assert "Stages: 1" in summary

    def test_summarize_bundle_flow_contains_task(self, tmp_path: Path) -> None:
        bundles_dir = tmp_path / "bundles"
        report = _flow_report()

        path = write_bundle(bundles_dir, "ship", "build the feature", report)
        summary = summarize_bundle(path)

        assert "build the feature" in summary


class TestSummarizeBundleRobustness:
    def test_malformed_bundle_raises_value_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.jsonl"
        bad.write_text("this is not json\n")
        with pytest.raises(ValueError):
            summarize_bundle(bad)

    def test_missing_bundle_raises_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            summarize_bundle(tmp_path / "nope.jsonl")
