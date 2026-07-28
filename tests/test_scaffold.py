# test_scaffold.py — Hermetic tests for scaffold.py and the `alc init` command.
from __future__ import annotations

import subprocess

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
    ".alc/.gitignore",
])


class TestScaffoldCreatesDefaultFiles:
    def test_scaffold_creates_default_files(self, tmp_path: Path) -> None:
        """scaffold() returns the expected relative paths and the files exist on disk."""
        created = scaffold(tmp_path)

        assert created == _EXPECTED_PATHS

        for rel in _EXPECTED_PATHS:
            assert (tmp_path / rel).is_file(), f"Missing: {rel}"


class TestScaffoldGitignoresRuntimeDirs:
    """`.alc/.gitignore` is an ALLOWLIST: track the CONFIG (a bounded, known set),
    ignore all other `.alc/` content — run-generated state — by default. This closes
    the whole class of "a new runtime dir was forgotten" gaps (a denylist leaked as
    features added runs/ → metrics/ → loop state → specialist knowledge → variants/)."""

    @staticmethod
    def _is_ignored(repo: Path, rel: str) -> bool:
        return (
            subprocess.run(
                ["git", "-C", str(repo), "check-ignore", "-q", rel],
                capture_output=True,
            ).returncode
            == 0
        )

    def _scaffolded_git_repo(self, tmp_path: Path) -> Path:
        scaffold(tmp_path)
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
        return tmp_path

    def test_config_is_tracked_runtime_is_ignored_including_a_future_dir(
        self, tmp_path: Path
    ) -> None:
        repo = self._scaffolded_git_repo(tmp_path)
        alc = repo / ".alc"
        # CONFIG (bounded, known) — plus a runtime file sharing loops/ & specialists/.
        for rel in ("loops", "specialists", "primers", "runs", "variants", "brandnewdir"):
            (alc / rel).mkdir(parents=True, exist_ok=True)
        (alc / "loops" / "sweep.yaml").write_text("name: sweep\n")
        (alc / "loops" / "sweep.state.json").write_text("{}")
        (alc / "specialists" / "deps.yaml").write_text("name: deps\n")
        (alc / "specialists" / "janitor.knowledge.md").write_text("learned\n")
        (alc / "primers" / "p.md").write_text("x\n")
        (alc / "runs" / "r.jsonl").write_text("{}\n")
        (alc / "variants" / "v.json").write_text("{}")
        (alc / "brandnewdir" / "f.dat").write_text("x")  # a HYPOTHETICAL future runtime dir

        # Config stays tracked — including the .gitignore itself and the mixed-dir .yaml.
        for rel in (
            ".alc/.gitignore",
            ".alc/manifest.yaml",
            ".alc/blueprints/chore.md",
            ".alc/flows/ship.yaml",
            ".alc/loops/sweep.yaml",
            ".alc/specialists/deps.yaml",
            ".alc/primers/p.md",
        ):
            assert not self._is_ignored(repo, rel), f"config wrongly ignored: {rel}"

        # Runtime is ignored — incl. the loop/specialist runtime AND a dir no rule names.
        for rel in (
            ".alc/runs/r.jsonl",
            ".alc/variants/v.json",
            ".alc/brandnewdir/f.dat",
            ".alc/loops/sweep.state.json",
            ".alc/specialists/janitor.knowledge.md",
        ):
            assert self._is_ignored(repo, rel), f"runtime wrongly tracked: {rel}"


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


class TestDetectStackMoreEcosystems:
    def test_ruby_gemfile_detected(self, tmp_path: Path) -> None:
        (tmp_path / "Gemfile").write_text("source 'https://rubygems.org'\n")
        label, checks = detect_stack(tmp_path)
        assert label == "Ruby"
        assert "rspec" in checks
        assert "rubocop" in checks

    def test_php_composer_json_detected(self, tmp_path: Path) -> None:
        (tmp_path / "composer.json").write_text('{"name": "vendor/pkg"}\n')
        label, checks = detect_stack(tmp_path)
        assert label == "PHP"
        assert "composer" in checks
        assert "phpstan" in checks

    def test_maven_pom_xml_detected(self, tmp_path: Path) -> None:
        (tmp_path / "pom.xml").write_text("<project></project>\n")
        label, checks = detect_stack(tmp_path)
        assert label == "Maven"
        assert "mvn" in checks
        assert "verify" in checks

    def test_gradle_groovy_detected(self, tmp_path: Path) -> None:
        (tmp_path / "build.gradle").write_text("plugins {}\n")
        label, checks = detect_stack(tmp_path)
        assert label == "Gradle"
        assert "gradlew" in checks

    def test_gradle_kotlin_detected(self, tmp_path: Path) -> None:
        (tmp_path / "build.gradle.kts").write_text("plugins {}\n")
        label, _checks = detect_stack(tmp_path)
        assert label == "Gradle"

    def test_elixir_mix_exs_detected(self, tmp_path: Path) -> None:
        (tmp_path / "mix.exs").write_text("defmodule X.MixProject do\nend\n")
        label, checks = detect_stack(tmp_path)
        assert label == "Elixir"
        assert "mix" in checks
        assert "credo" in checks

    def test_dotnet_csproj_glob_detected(self, tmp_path: Path) -> None:
        """detect_stack() matches a *.csproj file by glob, not exact name."""
        (tmp_path / "App.csproj").write_text("<Project></Project>\n")
        label, checks = detect_stack(tmp_path)
        assert label == ".NET"
        assert "dotnet" in checks

    def test_dotnet_sln_only_detected(self, tmp_path: Path) -> None:
        (tmp_path / "MyApp.sln").write_text("Microsoft Visual Studio Solution File\n")
        label, _checks = detect_stack(tmp_path)
        assert label == ".NET"

    def test_empty_dir_still_returns_default_block(self, tmp_path: Path) -> None:
        from alc.scaffold import _DEFAULT_CHECKS_BLOCK

        assert detect_stack(tmp_path) == (None, _DEFAULT_CHECKS_BLOCK)


class TestScaffoldRubyCheckSet:
    def test_ruby_only_project_writes_a_ruby_check_set(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A Gemfile-only project scaffolds a `ruby` check_set alongside `security`."""
        monkeypatch.setattr("alc.scaffold.shutil.which", lambda cmd: f"/usr/bin/{cmd}")
        (tmp_path / "Gemfile").write_text("source 'https://rubygems.org'\n")
        scaffold(tmp_path)

        manifest = load_manifest(tmp_path / ".alc")
        assert set(manifest.check_sets) == {"ruby", "security"}
        assert [c.name for c in manifest.check_sets["ruby"]] == ["test", "lint"]
        assert [c.name for c in manifest.check_sets["security"]] == ["bundler-audit", "gitleaks"]

    def test_ruby_check_set_entries_commented_when_binaries_absent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """No binary on PATH -> the ruby set renders every entry commented out."""
        monkeypatch.setattr("alc.scaffold.shutil.which", lambda cmd: None)
        (tmp_path / "Gemfile").write_text("source 'https://rubygems.org'\n")
        scaffold(tmp_path)

        manifest_text = (tmp_path / ".alc" / "manifest.yaml").read_text()
        assert "ruby:" in manifest_text
        assert "# - name: test" in manifest_text
        assert "# - name: lint" in manifest_text
        assert "# - name: bundler-audit" in manifest_text

        # A fully-commented set still parses as a valid (empty) list.
        manifest = load_manifest(tmp_path / ".alc")
        assert manifest.check_sets["ruby"] == []


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
    def test_python_project_blueprints_and_flow_unchanged(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """check_sets is new manifest.yaml content only — blueprints/flow don't move.

        The snapshot captures the ON-PATH rendering (a live `pytest -q` inline check),
        so `which` is forced present to keep this hermetic regardless of whether the
        test host actually has pytest bare on PATH.
        """
        monkeypatch.setattr("alc.scaffold.shutil.which", lambda cmd: f"/usr/bin/{cmd}")
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        scaffold(tmp_path)

        for rel, expected in _PYTHON_STACK_EXPECTED.items():
            assert (tmp_path / rel).read_text() == expected, f"{rel} changed by T5"


# ---------------------------------------------------------------------------
# A detected stack's INLINE blueprint check is PATH-aware, mirroring the
# check_sets rendering: a check whose binary is off PATH is commented out (with a
# smoke fallback) rather than shipped live-and-broken. This closes the divergence
# where init commented the check_set's pytest for the missing binary yet shipped
# the SAME pytest live in the blueprint (a run then 127s on a clean checkout).
# ---------------------------------------------------------------------------


class TestBlueprintChecksArePathAware:
    def test_empty_checks_returns_default_placeholder_block(self) -> None:
        """No detected stack -> the default `# Replace...` + smoke block, unchanged."""
        from alc.scaffold import _DEFAULT_CHECKS_BLOCK, render_blueprint_checks

        assert render_blueprint_checks([]) == _DEFAULT_CHECKS_BLOCK

    def test_on_path_is_byte_identical_to_hardcoded_block(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every binary on PATH -> live checks, no hint, no smoke fallback (unchanged)."""
        from alc.scaffold import render_blueprint_checks

        monkeypatch.setattr("alc.scaffold.shutil.which", lambda cmd: f"/usr/bin/{cmd}")
        block = render_blueprint_checks(
            [("build", ["go", "build", "./..."]), ("vet", ["go", "vet", "./..."])]
        )
        assert block == (
            '  - name: build\n    command: ["go", "build", "./..."]\n'
            '  - name: vet\n    command: ["go", "vet", "./..."]'
        )

    def test_off_path_is_commented_with_smoke_fallback_and_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No binary on PATH -> every check commented, smoke fallback added, hint shown."""
        from alc.scaffold import _BLUEPRINT_OFF_PATH_HINT, render_blueprint_checks

        monkeypatch.setattr("alc.scaffold.shutil.which", lambda cmd: None)
        block = render_blueprint_checks([("test", ["pytest", "-q"])])
        assert block.startswith(_BLUEPRINT_OFF_PATH_HINT)
        assert '  # - name: test' in block
        assert '  #   command: ["pytest", "-q"]' in block
        # The smoke fallback keeps the block a valid, honestly smoke-only check list.
        assert '  - name: smoke' in block
        assert '    command: ["true"]' in block

    def test_mixed_availability_keeps_live_and_comments_absent_no_smoke(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One binary present, one absent -> live + commented, hint, NO smoke fallback."""
        from alc.scaffold import render_blueprint_checks

        monkeypatch.setattr(
            "alc.scaffold.shutil.which",
            lambda cmd: "/usr/bin/rspec" if cmd == "bundle" else None,
        )
        block = render_blueprint_checks(
            [("test", ["bundle", "exec", "rspec"]), ("lint", ["ruff", "check", "."])]
        )
        assert '  - name: test' in block          # bundle on PATH -> live
        assert '  # - name: lint' in block         # ruff off PATH -> commented
        assert '- name: smoke' not in block        # a live check exists -> no fallback

    def test_python_scaffold_off_path_blueprints_are_smoke_only(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The crux: pytest off PATH -> chore/bug/feature scaffold as smoke-only, so a
        run cannot 127 AND `alc onboard` can opt them into a harvested check_set."""
        from alc.intake import is_smoke_only

        monkeypatch.setattr("alc.scaffold.shutil.which", lambda cmd: None)
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        scaffold(tmp_path)

        operator_layer = tmp_path / ".alc"
        manifest = load_manifest(operator_layer)
        blueprints = {bp.name: bp for bp in load_all_blueprints(manifest, operator_layer)}
        for name in ("chore", "bug", "feature"):
            assert is_smoke_only(manifest, blueprints[name]), f"{name} should be smoke-only"

        # And the degraded layer still lints clean (smoke is a valid live check).
        errors = [v for v in lint(manifest, list(blueprints.values())) if v.severity == "error"]
        assert not errors, f"off-PATH Python layer has lint errors: {errors}"

    def test_python_scaffold_on_path_blueprints_run_pytest(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """pytest on PATH -> the blueprint keeps a real (non-smoke) pytest check."""
        from alc.intake import is_smoke_only

        monkeypatch.setattr("alc.scaffold.shutil.which", lambda cmd: f"/usr/bin/{cmd}")
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        scaffold(tmp_path)

        operator_layer = tmp_path / ".alc"
        manifest = load_manifest(operator_layer)
        blueprints = {bp.name: bp for bp in load_all_blueprints(manifest, operator_layer)}
        assert not is_smoke_only(manifest, blueprints["chore"])
        assert blueprints["chore"].checks[0].command == ["pytest", "-q"]


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
        # Real scripts so the Node battery stays live (an absent script is now
        # scaffolded commented out — exercised by TestScaffoldNodeChecksReflectRealScripts).
        (tmp_path / "package.json").write_text(
            '{"name": "x", "scripts": {"test": "jest", "lint": "eslint .", '
            '"typecheck": "tsc --noEmit"}}\n'
        )
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


# ---------------------------------------------------------------------------
# Part B — `alc init` scaffolds worktree_provision for Node so the default
# Node setup does not 127 on a fresh worktree (node_modules is gitignored).
# ---------------------------------------------------------------------------


class TestScaffoldNodeWorktreeProvision:
    def test_node_project_scaffolds_node_modules_link(self, tmp_path: Path) -> None:
        """A Node project links node_modules into every isolated worktree."""
        (tmp_path / "package.json").write_text('{"name": "myapp"}\n')
        scaffold(tmp_path)

        manifest = load_manifest(tmp_path / ".alc")
        assert len(manifest.worktree_provision) == 1
        spec = manifest.worktree_provision[0]
        assert spec.kind == "link"
        assert spec.path == "node_modules"

    def test_non_node_project_has_no_worktree_provision(self, tmp_path: Path) -> None:
        """A stack with no known gitignored dep dir gets no provision block."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        scaffold(tmp_path)

        manifest = load_manifest(tmp_path / ".alc")
        assert manifest.worktree_provision == []

    def test_no_stack_has_no_worktree_provision(self, tmp_path: Path) -> None:
        """An empty project stays byte-identical: no provision block."""
        scaffold(tmp_path)

        manifest = load_manifest(tmp_path / ".alc")
        assert manifest.worktree_provision == []

    def test_polyglot_including_node_gets_node_modules(self, tmp_path: Path) -> None:
        """A python + node project still links node_modules (Node is present)."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        (tmp_path / "package.json").write_text('{"name": "x"}\n')
        scaffold(tmp_path)

        manifest = load_manifest(tmp_path / ".alc")
        assert [s.path for s in manifest.worktree_provision] == ["node_modules"]

    def test_node_scaffold_still_lints_clean(self, tmp_path: Path) -> None:
        """The Node layer with worktree_provision passes the Policy Gate."""
        (tmp_path / "package.json").write_text('{"name": "x"}\n')
        scaffold(tmp_path)

        operator_layer = tmp_path / ".alc"
        manifest = load_manifest(operator_layer)
        blueprints = load_all_blueprints(manifest, operator_layer)
        violations = lint(manifest, blueprints)
        errors = [v for v in violations if v.severity == "error"]
        assert not errors, f"Policy Gate errors on Node layer: {errors}"

    def test_node_provision_declares_refresh(self, tmp_path: Path) -> None:
        """The scaffolded Node provision carries the deps-refresh trigger + install
        so a dependency bump can never land a false green against stale packages."""
        (tmp_path / "package.json").write_text('{"name": "x"}\n')
        scaffold(tmp_path)

        manifest = load_manifest(tmp_path / ".alc")
        spec = manifest.worktree_provision[0]
        assert spec.refresh == ["npm", "install"]
        assert spec.when_changed == ["package.json", "package-lock.json"]

    def test_node_provision_sniffs_pnpm(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name": "x"}\n')
        (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: 6.0\n")
        scaffold(tmp_path)

        spec = load_manifest(tmp_path / ".alc").worktree_provision[0]
        assert spec.refresh == ["pnpm", "install"]
        assert spec.when_changed == ["package.json", "pnpm-lock.yaml"]

    def test_node_provision_sniffs_yarn(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name": "x"}\n')
        (tmp_path / "yarn.lock").write_text("# yarn lockfile v1\n")
        scaffold(tmp_path)

        spec = load_manifest(tmp_path / ".alc").worktree_provision[0]
        assert spec.refresh == ["yarn", "install"]
        assert spec.when_changed == ["package.json", "yarn.lock"]


# ---------------------------------------------------------------------------
# The Node check_set must reflect the project's REAL package.json scripts. A
# scaffolded `npm run <script>` for a script the project does not have would fail
# EVERY run with "Missing script" — it cannot be law, so an absent script is
# scaffolded commented out (the same treatment an off-PATH binary already gets).
# All tests force `npm` onto PATH so the ONLY reason a check is commented is a
# missing script, isolating the new behavior from binary availability.
# ---------------------------------------------------------------------------


def _write_node_package(tmp_path: Path, scripts: dict[str, str] | None) -> None:
    """Write a package.json, with a `scripts` map only when *scripts* is given."""
    import json as _json

    payload: dict[str, object] = {"name": "myapp"}
    if scripts is not None:
        payload["scripts"] = scripts
    (tmp_path / "package.json").write_text(_json.dumps(payload) + "\n")


def _node_check(manifest, name: str):  # type: ignore[no-untyped-def]
    """The live Check named *name* in the `node` set, or None if absent/commented."""
    for check in manifest.check_sets.get("node", []):
        if check.name == name:
            return check
    return None


class TestScaffoldNodeChecksReflectRealScripts:
    def test_type_check_variant_is_scaffolded_live(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """`type-check` (not `typecheck`) resolves to `npm run type-check`, live."""
        monkeypatch.setattr("alc.scaffold.shutil.which", lambda cmd: f"/usr/bin/{cmd}")
        _write_node_package(tmp_path, {"type-check": "tsc --noEmit"})
        scaffold(tmp_path)

        manifest = load_manifest(tmp_path / ".alc")
        typecheck = _node_check(manifest, "typecheck")
        assert typecheck is not None, "typecheck must be live when type-check exists"
        assert typecheck.command == ["npm", "run", "type-check"]

        manifest_text = (tmp_path / ".alc" / "manifest.yaml").read_text()
        assert '    - name: typecheck\n      command: ["npm", "run", "type-check"]' in manifest_text
        assert "npm\", \"run\", \"typecheck\"" not in manifest_text

    def test_canonical_typecheck_script_used_verbatim(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A canonical `typecheck` script resolves to `npm run typecheck`."""
        monkeypatch.setattr("alc.scaffold.shutil.which", lambda cmd: f"/usr/bin/{cmd}")
        _write_node_package(tmp_path, {"typecheck": "tsc --noEmit"})
        scaffold(tmp_path)

        manifest = load_manifest(tmp_path / ".alc")
        typecheck = _node_check(manifest, "typecheck")
        assert typecheck is not None
        assert typecheck.command == ["npm", "run", "typecheck"]

    def test_type_colon_check_variant_resolved(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The `type:check` spelling is also resolved."""
        monkeypatch.setattr("alc.scaffold.shutil.which", lambda cmd: f"/usr/bin/{cmd}")
        _write_node_package(tmp_path, {"type:check": "tsc --noEmit"})
        scaffold(tmp_path)

        manifest = load_manifest(tmp_path / ".alc")
        typecheck = _node_check(manifest, "typecheck")
        assert typecheck is not None
        assert typecheck.command == ["npm", "run", "type:check"]

    def test_canonical_wins_over_variants_by_priority(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """When several spellings exist, `typecheck` wins (first in priority order)."""
        monkeypatch.setattr("alc.scaffold.shutil.which", lambda cmd: f"/usr/bin/{cmd}")
        _write_node_package(
            tmp_path, {"typecheck": "tsc", "type-check": "tsc", "type:check": "tsc"}
        )
        scaffold(tmp_path)

        typecheck = _node_check(load_manifest(tmp_path / ".alc"), "typecheck")
        assert typecheck is not None
        assert typecheck.command == ["npm", "run", "typecheck"]

    def test_present_test_stays_live_absent_lint_typecheck_commented(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Only `test` exists -> it stays live; lint + typecheck are commented out."""
        monkeypatch.setattr("alc.scaffold.shutil.which", lambda cmd: f"/usr/bin/{cmd}")
        _write_node_package(tmp_path, {"test": "jest"})
        scaffold(tmp_path)

        manifest = load_manifest(tmp_path / ".alc")
        assert [c.name for c in manifest.check_sets["node"]] == ["test"]
        assert _node_check(manifest, "test").command == ["npm", "test"]

        manifest_text = (tmp_path / ".alc" / "manifest.yaml").read_text()
        assert '    - name: test\n      command: ["npm", "test"]' in manifest_text
        assert "# - name: lint" in manifest_text
        assert "# - name: typecheck" in manifest_text

    def test_missing_test_script_comments_out_npm_test(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """No `test` script -> `npm test` (which would error "Missing script") is commented."""
        monkeypatch.setattr("alc.scaffold.shutil.which", lambda cmd: f"/usr/bin/{cmd}")
        _write_node_package(tmp_path, {"lint": "eslint ."})
        scaffold(tmp_path)

        manifest = load_manifest(tmp_path / ".alc")
        assert [c.name for c in manifest.check_sets["node"]] == ["lint"]

        manifest_text = (tmp_path / ".alc" / "manifest.yaml").read_text()
        assert "# - name: test" in manifest_text
        assert '    - name: lint\n      command: ["npm", "run", "lint"]' in manifest_text

    def test_no_scripts_key_degrades_to_all_commented(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A package.json with no `scripts` key -> the whole node set is commented out."""
        monkeypatch.setattr("alc.scaffold.shutil.which", lambda cmd: f"/usr/bin/{cmd}")
        _write_node_package(tmp_path, None)
        scaffold(tmp_path)

        manifest = load_manifest(tmp_path / ".alc")
        assert manifest.check_sets["node"] == []

    def test_malformed_package_json_degrades_without_raising(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Malformed JSON must not raise; the node set degrades to all-commented."""
        monkeypatch.setattr("alc.scaffold.shutil.which", lambda cmd: f"/usr/bin/{cmd}")
        (tmp_path / "package.json").write_text("{ this is not valid json ")
        scaffold(tmp_path)  # must not raise

        manifest = load_manifest(tmp_path / ".alc")
        assert manifest.check_sets["node"] == []

    def test_every_case_still_lints_clean(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The scaffolded manifest parses and lints clean whether scripts are live or absent."""
        monkeypatch.setattr("alc.scaffold.shutil.which", lambda cmd: f"/usr/bin/{cmd}")
        _write_node_package(tmp_path, {"type-check": "tsc --noEmit"})
        scaffold(tmp_path)

        operator_layer = tmp_path / ".alc"
        manifest = load_manifest(operator_layer)
        blueprints = load_all_blueprints(manifest, operator_layer)
        errors = [v for v in lint(manifest, blueprints) if v.severity == "error"]
        assert not errors, f"Policy Gate errors on Node layer: {errors}"
