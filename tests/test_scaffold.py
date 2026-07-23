# test_scaffold.py — Hermetic tests for scaffold.py and the `alc init` command.
from __future__ import annotations

import pytest
from pathlib import Path

from alc.scaffold import detect_stack, scaffold
from alc.intake import load_all_blueprints, load_flow, load_manifest
from alc.policy import lint


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


# ---------------------------------------------------------------------------
# Stack detection — Node and Rust stacks, plus precedence
# ---------------------------------------------------------------------------


class TestDetectStackNode:
    def test_package_json_detected(self, tmp_path: Path) -> None:
        """detect_stack() returns ('Node', ...) when package.json is present."""
        (tmp_path / "package.json").write_text('{"name": "myapp"}\n')
        label, _checks = detect_stack(tmp_path)
        assert label == "Node"

    def test_node_checks_block_contains_npm_test(self, tmp_path: Path) -> None:
        """Node checks block references npm test."""
        (tmp_path / "package.json").write_text('{"name": "myapp"}\n')
        _label, checks = detect_stack(tmp_path)
        assert "npm" in checks
        assert "test" in checks


class TestDetectStackRust:
    def test_cargo_toml_detected(self, tmp_path: Path) -> None:
        """detect_stack() returns ('Rust', ...) when Cargo.toml is present."""
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "hello"\n')
        label, _checks = detect_stack(tmp_path)
        assert label == "Rust"

    def test_rust_checks_block_contains_cargo_check(self, tmp_path: Path) -> None:
        """Rust checks block references cargo check."""
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "hello"\n')
        _label, checks = detect_stack(tmp_path)
        assert "cargo" in checks
        assert "check" in checks


class TestDetectStackPrecedence:
    def test_go_wins_over_pyproject(self, tmp_path: Path) -> None:
        """go.mod takes precedence over pyproject.toml when both are present."""
        (tmp_path / "go.mod").write_text("module example\n")
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        label, _checks = detect_stack(tmp_path)
        assert label == "Go"


# ---------------------------------------------------------------------------
# check_sets — alc init writes one named set per detected stack + `security`
# ---------------------------------------------------------------------------


# Byte-exact blueprint/flow content for a single-stack (Python) project, captured
# from scaffold() BEFORE check_sets existed. `alc init` on a single-stack project
# must still produce these files byte-identical — check_sets is new content in
# manifest.yaml only, never a change to the blueprints/flow the older behavior
# already produced.
_PYTHON_STACK_EXPECTED = {
    ".alc/blueprints/chore.md": (
        '---\nname: chore\npurpose: Apply a low-risk, well-scoped maintenance change.\n'
        'compute_tier: standard\nchecks:\n  - name: test\n    command: ["pytest", "-q"]\n'
        'report:\n  format: json\n  schema:\n    status: string\n    summary: string\n---\n\n'
        '## Chore Workflow\n\n1. Read the task description and locate the relevant files.\n'
        '2. Make the smallest change that satisfies the task; keep it single-purpose.\n'
        '3. Do not touch files outside the stated scope.\n'
        '4. Run the checks to verify correctness.\n'
        '5. Output a JSON report matching the schema:\n   ```json\n'
        '   {"status": "ok", "summary": "<one sentence describing what was done>"}\n'
        '   ```\n'
    ),
    ".alc/blueprints/bug.md": (
        '---\nname: bug\npurpose: Diagnose and fix a bug.\ncompute_tier: standard\n'
        'checks:\n  - name: test\n    command: ["pytest", "-q"]\nreport:\n  format: json\n'
        '  schema:\n    status: string\n    root_cause: string\n    fix: string\n'
        '    summary: string\n---\n\n## Bug Workflow\n\n'
        '1. Reproduce the bug using the information in the task description.\n'
        '2. Find the root cause — trace it to the smallest possible location.\n'
        '3. Apply the smallest fix that resolves the root cause without side effects.\n'
        '4. Validate the fix by running the checks.\n'
        '5. Output a JSON report matching the schema:\n   ```json\n   {\n'
        '     "status": "ok",\n     "root_cause": "<what caused the bug>",\n'
        '     "fix": "<what was changed>",\n     "summary": "<one sentence summary>"\n'
        '   }\n   ```\n'
    ),
    ".alc/blueprints/feature.md": (
        '---\nname: feature\npurpose: Implement a new feature.\ncompute_tier: deep\n'
        'checks:\n  - name: test\n    command: ["pytest", "-q"]\nreport:\n  format: json\n'
        '  schema:\n    status: string\n    summary: string\n---\n\n## Feature Workflow\n\n'
        '1. Understand the requirement stated in the task description.\n'
        '2. Design the smallest viable approach that satisfies the requirement.\n'
        '3. Implement the feature following the existing code style and conventions.\n'
        '4. Verify the implementation by running the checks.\n'
        '5. Output a JSON report matching the schema:\n   ```json\n'
        '   {"status": "ok", "summary": "<one sentence describing what was implemented>"}\n'
        '   ```\n'
    ),
    ".alc/blueprints/plan.md": (
        '---\nname: plan\npurpose: Produce a focused implementation plan.\n'
        'compute_tier: deep\nchecks:\n'
        '  # Replace this with your real checks, e.g. ["ruff", "check", "."] and '
        '["pytest", "-q"]\n  - name: smoke\n    command: ["true"]\nreport:\n  format: json\n'
        '  schema:\n    plan: string\n---\n\n## Plan Workflow\n\n'
        '1. Read the task description and any relevant files to understand the scope.\n'
        '2. Produce a concise, numbered step-by-step implementation plan.\n'
        '3. Each step should be actionable and independently verifiable.\n'
        '4. Do NOT write application code in this stage — planning only.\n'
        '5. Output a JSON report matching the schema:\n   ```json\n'
        '   {"plan": "<the full step-by-step plan as text>"}\n   ```\n'
    ),
    ".alc/flows/ship.yaml": (
        'name: ship\ndescription: Plan a change, then implement it — each stage its '
        'own mandate.\nstages:\n  - name: plan\n    blueprint: plan\n  - name: build\n'
        '    blueprint: feature\n'
    ),
}


class TestScaffoldBlueprintsStayByteIdenticalWithCheckSets:
    def test_python_project_blueprints_and_flow_unchanged(self, tmp_path: Path) -> None:
        """check_sets is new manifest.yaml content only — blueprints/flow don't move."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        scaffold(tmp_path)

        for rel, expected in _PYTHON_STACK_EXPECTED.items():
            assert (tmp_path / rel).read_text() == expected, f"{rel} changed by T5"


class TestScaffoldWritesCheckSets:
    def test_python_project_gets_python_and_security_sets(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Every command resolves on PATH -> both sets are written live."""
        monkeypatch.setattr("alc.scaffold.shutil.which", lambda cmd: f"/usr/bin/{cmd}")
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        scaffold(tmp_path)

        manifest = load_manifest(tmp_path / ".alc")
        assert set(manifest.check_sets) == {"python", "security"}
        assert [c.name for c in manifest.check_sets["python"]] == ["test", "lint"]
        assert [c.command for c in manifest.check_sets["python"]] == [
            ["pytest", "-q"], ["ruff", "check", "."],
        ]
        security_names = [c.name for c in manifest.check_sets["security"]]
        assert security_names == ["pip-audit", "gitleaks"]

    def test_no_stack_still_gets_security_set(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """gitleaks is stack-agnostic: an empty project still gets a `security` set."""
        monkeypatch.setattr("alc.scaffold.shutil.which", lambda cmd: f"/usr/bin/{cmd}")
        scaffold(tmp_path)

        manifest = load_manifest(tmp_path / ".alc")
        assert set(manifest.check_sets) == {"security"}
        assert [c.name for c in manifest.check_sets["security"]] == ["gitleaks"]

    def test_polyglot_project_gets_a_set_per_stack(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A python + node project gets BOTH check_sets, not just the first match."""
        monkeypatch.setattr("alc.scaffold.shutil.which", lambda cmd: f"/usr/bin/{cmd}")
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        (tmp_path / "package.json").write_text('{"name": "x"}\n')
        scaffold(tmp_path)

        manifest = load_manifest(tmp_path / ".alc")
        assert set(manifest.check_sets) == {"python", "node", "security"}
        assert [c.name for c in manifest.check_sets["node"]] == ["test", "lint", "typecheck"]
        security_names = {c.name for c in manifest.check_sets["security"]}
        assert security_names == {"pip-audit", "npm-audit", "gitleaks"}


class TestScaffoldChecksSetsCommentOutMissingBinaries:
    def test_missing_binary_is_written_commented_not_live(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """No binary at all is on PATH -> the security set ends up empty (all commented)."""
        monkeypatch.setattr("alc.scaffold.shutil.which", lambda cmd: None)
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        scaffold(tmp_path)

        manifest_text = (tmp_path / ".alc" / "manifest.yaml").read_text()
        assert '# - name: pip-audit' in manifest_text
        assert '#   command: ["pip-audit"]' in manifest_text
        assert '# - name: gitleaks' in manifest_text

        # A commented-out set still parses as a Manifest with a valid (empty) list.
        manifest = load_manifest(tmp_path / ".alc")
        assert manifest.check_sets["security"] == []

    def test_only_missing_binaries_are_commented_others_stay_live(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """pytest present, ruff absent -> test stays live, lint is commented."""
        available = {"pytest"}
        monkeypatch.setattr(
            "alc.scaffold.shutil.which",
            lambda cmd: "/usr/bin/pytest" if cmd in available else None,
        )
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        scaffold(tmp_path)

        manifest = load_manifest(tmp_path / ".alc")
        assert [c.name for c in manifest.check_sets["python"]] == ["test"]

        manifest_text = (tmp_path / ".alc" / "manifest.yaml").read_text()
        assert '    - name: test\n      command: ["pytest", "-q"]' in manifest_text
        assert '# - name: lint' in manifest_text

    def test_scaffolded_layer_with_check_sets_still_lints_clean(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """check_sets are dormant (no default blueprint references them) — lint stays green."""
        monkeypatch.setattr("alc.scaffold.shutil.which", lambda cmd: None)
        (tmp_path / "go.mod").write_text("module example\n")
        scaffold(tmp_path)

        operator_layer = tmp_path / ".alc"
        manifest = load_manifest(operator_layer)
        blueprints = load_all_blueprints(manifest, operator_layer)
        violations = lint(manifest, blueprints)
        errors = [v for v in violations if v.severity == "error"]
        assert not errors, f"Policy Gate errors with check_sets present: {errors}"
