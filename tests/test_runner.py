# test_runner.py — End-to-end test via MandateRunner using the real .alc/ manifest
# and chore blueprint with --engine mock. Hermetic: no real model called.
from __future__ import annotations

import json
from pathlib import Path

import pytest

from alc.intake import load_blueprint, load_manifest
from alc.models import RunReport
from alc.runner import MandateRunner


def _operator_layer() -> Path:
    """Locate the .alc/ directory relative to this test file."""
    # Tests run from the repo root; .alc/ is at repo_root/.alc/
    repo_root = Path(__file__).parent.parent
    return repo_root / ".alc"


class TestMandateRunnerEndToEnd:
    def test_chore_blueprint_with_mock_engine_succeeds(self) -> None:
        operator_layer = _operator_layer()
        manifest = load_manifest(operator_layer)

        blueprints_dir = operator_layer.parent / manifest.blueprints_dir
        blueprint = load_blueprint(blueprints_dir, "chore")

        runner = MandateRunner(manifest=manifest, operator_layer=operator_layer)
        report = runner.run(
            blueprint=blueprint,
            task="remove the unused export endpoint",
            engine_override="mock",
        )

        assert report.success is True
        assert report.engine == "mock"
        assert report.blueprint == "chore"

        # RunReport must be serialisable to JSON.
        raw = json.loads(report.model_dump_json())
        assert raw["success"] is True
        assert raw["scorecard"]["passes"] >= 1

    def test_report_scorecard_fields_present(self) -> None:
        operator_layer = _operator_layer()
        manifest = load_manifest(operator_layer)
        blueprints_dir = operator_layer.parent / manifest.blueprints_dir
        blueprint = load_blueprint(blueprints_dir, "chore")

        runner = MandateRunner(manifest=manifest, operator_layer=operator_layer)
        report = runner.run(blueprint=blueprint, task="tidy imports", engine_override="mock")

        sc = report.scorecard
        assert sc.span >= 0
        assert sc.passes >= 1
        assert sc.streak in (0, 1)
        assert sc.touch == 0
