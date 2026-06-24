# test_scaffold.py — Hermetic tests for scaffold.py and the `alc init` command.
from __future__ import annotations

import pytest
from pathlib import Path

from alc.scaffold import scaffold
from alc.intake import load_all_blueprints, load_flow, load_manifest
from alc.policy import has_errors, lint


# Expected relative paths produced by scaffold().
_EXPECTED_PATHS = sorted([
    ".alc/manifest.yaml",
    ".alc/blueprints/chore.md",
    ".alc/blueprints/bug.md",
    ".alc/blueprints/feature.md",
    ".alc/blueprints/plan.md",
    ".alc/flows/ship.yaml",
])


class TestScaffoldCreatesDefaultFiles:
    def test_scaffold_creates_default_files(self, tmp_path: Path) -> None:
        """scaffold() returns the expected relative paths and the files exist on disk."""
        created = scaffold(tmp_path)

        assert created == _EXPECTED_PATHS

        for rel in _EXPECTED_PATHS:
            assert (tmp_path / rel).is_file(), f"Missing: {rel}"


class TestScaffoldOutputIsConformant:
    def test_scaffold_output_is_conformant(self, tmp_path: Path) -> None:
        """The built-in defaults pass lint() with no error-level violations."""
        scaffold(tmp_path)

        operator_layer = tmp_path / ".alc"
        manifest = load_manifest(operator_layer)
        blueprints = load_all_blueprints(manifest, operator_layer)

        # We should have exactly four blueprints.
        assert len(blueprints) == 4

        violations = lint(manifest, blueprints)
        errors = [v for v in violations if v.severity == "error"]
        assert not errors, f"Policy Gate errors on default layer: {errors}"


class TestScaffoldLoadsFlow:
    def test_scaffold_loads_flow(self, tmp_path: Path) -> None:
        """The default ship flow parses and references plan + feature."""
        scaffold(tmp_path)

        flows_dir = tmp_path / ".alc" / "flows"
        flow = load_flow(flows_dir, "ship")

        assert flow.name == "ship"
        assert len(flow.stages) == 2

        blueprints_in_stages = [s.blueprint for s in flow.stages]
        assert "plan" in blueprints_in_stages
        assert "feature" in blueprints_in_stages


class TestScaffoldRefusesExistingWithoutForce:
    def test_scaffold_refuses_existing_without_force(self, tmp_path: Path) -> None:
        """scaffold() raises FileExistsError when .alc/ exists and force is False."""
        alc_dir = tmp_path / ".alc"
        alc_dir.mkdir()

        with pytest.raises(FileExistsError):
            scaffold(tmp_path)

    def test_scaffold_force_overwrites_existing(self, tmp_path: Path) -> None:
        """scaffold(force=True) succeeds even when .alc/ already exists."""
        alc_dir = tmp_path / ".alc"
        alc_dir.mkdir()

        created = scaffold(tmp_path, force=True)

        assert created == _EXPECTED_PATHS
        for rel in _EXPECTED_PATHS:
            assert (tmp_path / rel).is_file(), f"Missing after force: {rel}"
