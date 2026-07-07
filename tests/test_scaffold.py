# test_scaffold.py — Hermetic tests for scaffold.py and the `alc init` command.
from __future__ import annotations

import pytest
from pathlib import Path

from alc.scaffold import detect_stack, scaffold
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


# ---------------------------------------------------------------------------
# Stack detection tests
# ---------------------------------------------------------------------------


class TestDetectStackGoMod:
    def test_go_mod_detected(self, tmp_path: Path) -> None:
        """detect_stack() returns ('Go', ...) when go.mod is present."""
        (tmp_path / "go.mod").write_text("module example\n")
        label, _checks = detect_stack(tmp_path)
        assert label == "Go"

    def test_go_checks_block_contains_go_build(self, tmp_path: Path) -> None:
        """Go checks block references the go build command."""
        (tmp_path / "go.mod").write_text("module example\n")
        _label, checks = detect_stack(tmp_path)
        assert "build" in checks
        assert '"go"' in checks

    def test_go_checks_block_contains_go_vet(self, tmp_path: Path) -> None:
        """Go checks block references the go vet command."""
        (tmp_path / "go.mod").write_text("module example\n")
        _label, checks = detect_stack(tmp_path)
        assert "vet" in checks


class TestDetectStackPython:
    def test_pyproject_toml_detected(self, tmp_path: Path) -> None:
        """detect_stack() returns ('Python', ...) when pyproject.toml is present."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        label, _checks = detect_stack(tmp_path)
        assert label == "Python"

    def test_setup_py_detected(self, tmp_path: Path) -> None:
        """detect_stack() returns ('Python', ...) when setup.py is present."""
        (tmp_path / "setup.py").write_text("from setuptools import setup; setup()\n")
        label, _checks = detect_stack(tmp_path)
        assert label == "Python"

    def test_python_checks_block_contains_pytest(self, tmp_path: Path) -> None:
        """Python checks block includes pytest."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        _label, checks = detect_stack(tmp_path)
        assert "pytest" in checks


class TestDetectStackNoMatch:
    def test_empty_dir_returns_none(self, tmp_path: Path) -> None:
        """detect_stack() returns (None, ...) for an empty directory."""
        label, _checks = detect_stack(tmp_path)
        assert label is None

    def test_empty_dir_placeholder_block_has_smoke(self, tmp_path: Path) -> None:
        """Default checks block keeps the '# Replace...' comment and smoke check."""
        _label, checks = detect_stack(tmp_path)
        assert "Replace this" in checks
        assert '"true"' in checks


class TestScaffoldGoProjectConformant:
    def test_go_project_blueprints_have_go_checks(self, tmp_path: Path) -> None:
        """chore.md and feature.md reference go build + go vet when go.mod is present."""
        (tmp_path / "go.mod").write_text("module example\n")
        scaffold(tmp_path)

        for name in ("chore", "feature"):
            content = (tmp_path / ".alc" / "blueprints" / f"{name}.md").read_text()
            # Commands are stored as YAML lists: ["go", "build", "./..."]
            assert '"go"' in content, f"{name}.md missing go command reference"
            assert "build" in content, f"{name}.md missing build check"
            assert "vet" in content, f"{name}.md missing vet check"

    def test_go_project_plan_keeps_smoke_check(self, tmp_path: Path) -> None:
        """plan.md always keeps ['true'] smoke check regardless of stack."""
        (tmp_path / "go.mod").write_text("module example\n")
        scaffold(tmp_path)

        plan_content = (tmp_path / ".alc" / "blueprints" / "plan.md").read_text()
        assert '"true"' in plan_content

    def test_go_project_layer_lints_conformant(self, tmp_path: Path) -> None:
        """Scaffolded Go layer passes lint with no error-level violations."""
        (tmp_path / "go.mod").write_text("module example\n")
        scaffold(tmp_path)

        operator_layer = tmp_path / ".alc"
        manifest = load_manifest(operator_layer)
        blueprints = load_all_blueprints(manifest, operator_layer)
        violations = lint(manifest, blueprints)
        errors = [v for v in violations if v.severity == "error"]
        assert not errors, f"Policy Gate errors on Go layer: {errors}"


class TestScaffoldPythonProject:
    def test_python_project_blueprints_have_pytest(self, tmp_path: Path) -> None:
        """chore.md and feature.md contain pytest when pyproject.toml is present."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        scaffold(tmp_path)

        for name in ("chore", "feature"):
            content = (tmp_path / ".alc" / "blueprints" / f"{name}.md").read_text()
            assert "pytest" in content, f"{name}.md missing pytest check"
