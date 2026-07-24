# test_detect_stack.py — Tests for detect_stacks(): multi-stack detection with
# fuller check batteries. detect_stack() (the original 2-tuple, first-match-wins
# function) keeps its own coverage in test_scaffold.py.
from __future__ import annotations

from pathlib import Path

from alc.scaffold import detect_stacks


class TestDetectStacksEmpty:
    def test_empty_dir_returns_no_stacks(self, tmp_path: Path) -> None:
        assert detect_stacks(tmp_path) == []


class TestDetectStacksSingleStackBatteries:
    def test_go_battery_has_build_vet_test(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("module example\n")
        stacks = detect_stacks(tmp_path)
        assert len(stacks) == 1
        label, set_name, checks = stacks[0]
        assert label == "Go"
        assert set_name == "go"
        assert [name for name, _cmd in checks] == ["build", "vet", "test"]

    def test_python_battery_has_test_and_lint(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        _label, set_name, checks = detect_stacks(tmp_path)[0]
        assert set_name == "python"
        assert [name for name, _cmd in checks] == ["test", "lint"]

    def test_setup_py_also_detected_as_python(self, tmp_path: Path) -> None:
        (tmp_path / "setup.py").write_text("from setuptools import setup; setup()\n")
        stacks = detect_stacks(tmp_path)
        assert [set_name for _label, set_name, _checks in stacks] == ["python"]

    def test_node_battery_has_test_lint_typecheck(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name": "x"}\n')
        _label, set_name, checks = detect_stacks(tmp_path)[0]
        assert set_name == "node"
        assert [name for name, _cmd in checks] == ["test", "lint", "typecheck"]

    def test_rust_battery_has_check_test_clippy(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "x"\n')
        _label, set_name, checks = detect_stacks(tmp_path)[0]
        assert set_name == "rust"
        assert [name for name, _cmd in checks] == ["check", "test", "clippy"]


class TestDetectStacksMoreEcosystems:
    def test_ruby_battery_has_test_and_lint(self, tmp_path: Path) -> None:
        (tmp_path / "Gemfile").write_text("source 'https://rubygems.org'\n")
        [(label, set_name, checks)] = detect_stacks(tmp_path)
        assert label == "Ruby"
        assert set_name == "ruby"
        assert [name for name, _cmd in checks] == ["test", "lint"]
        assert dict(checks)["test"] == ["bundle", "exec", "rspec"]
        assert dict(checks)["lint"] == ["bundle", "exec", "rubocop"]

    def test_php_battery_has_test_and_analyse(self, tmp_path: Path) -> None:
        (tmp_path / "composer.json").write_text('{"name": "vendor/pkg"}\n')
        [(label, set_name, checks)] = detect_stacks(tmp_path)
        assert label == "PHP"
        assert set_name == "php"
        assert [name for name, _cmd in checks] == ["test", "analyse"]
        assert dict(checks)["analyse"] == ["vendor/bin/phpstan", "analyse"]

    def test_maven_battery_has_test_and_verify(self, tmp_path: Path) -> None:
        (tmp_path / "pom.xml").write_text("<project></project>\n")
        [(label, set_name, checks)] = detect_stacks(tmp_path)
        assert label == "Maven"
        assert set_name == "maven"
        assert [name for name, _cmd in checks] == ["test", "verify"]
        assert dict(checks)["test"] == ["mvn", "-q", "test"]

    def test_gradle_groovy_build_file_detected(self, tmp_path: Path) -> None:
        (tmp_path / "build.gradle").write_text("plugins {}\n")
        [(label, set_name, checks)] = detect_stacks(tmp_path)
        assert label == "Gradle"
        assert set_name == "gradle"
        assert [name for name, _cmd in checks] == ["test", "check"]
        assert dict(checks)["check"] == ["./gradlew", "check"]

    def test_gradle_kotlin_build_file_detected(self, tmp_path: Path) -> None:
        (tmp_path / "build.gradle.kts").write_text("plugins {}\n")
        [(_label, set_name, _checks)] = detect_stacks(tmp_path)
        assert set_name == "gradle"

    def test_elixir_battery_has_test_and_credo(self, tmp_path: Path) -> None:
        (tmp_path / "mix.exs").write_text("defmodule X.MixProject do\nend\n")
        [(label, set_name, checks)] = detect_stacks(tmp_path)
        assert label == "Elixir"
        assert set_name == "elixir"
        assert [name for name, _cmd in checks] == ["test", "credo"]
        assert dict(checks)["credo"] == ["mix", "credo"]

    def test_dotnet_csproj_glob_marker_detected(self, tmp_path: Path) -> None:
        """The .NET marker is a GLOB — any *.csproj file matches, not an exact name."""
        (tmp_path / "App.csproj").write_text("<Project></Project>\n")
        [(label, set_name, checks)] = detect_stacks(tmp_path)
        assert label == ".NET"
        assert set_name == "dotnet"
        assert [name for name, _cmd in checks] == ["build", "test"]
        assert dict(checks)["build"] == ["dotnet", "build"]

    def test_dotnet_sln_only_project_also_matches(self, tmp_path: Path) -> None:
        (tmp_path / "MyApp.sln").write_text("Microsoft Visual Studio Solution File\n")
        [(_label, set_name, _checks)] = detect_stacks(tmp_path)
        assert set_name == "dotnet"


class TestDetectStacksMulti:
    def test_python_and_node_both_detected(self, tmp_path: Path) -> None:
        """A polyglot project keeps BOTH stacks — the first-match-wins gap is fixed."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        (tmp_path / "package.json").write_text('{"name": "x"}\n')
        stacks = detect_stacks(tmp_path)
        assert [set_name for _label, set_name, _checks in stacks] == ["python", "node"]

    def test_gemfile_and_package_json_polyglot_returns_both(self, tmp_path: Path) -> None:
        """A new ecosystem coexists with a built-in one — node precedes ruby by order."""
        (tmp_path / "Gemfile").write_text("source 'https://rubygems.org'\n")
        (tmp_path / "package.json").write_text('{"name": "x"}\n')
        stacks = detect_stacks(tmp_path)
        assert [set_name for _label, set_name, _checks in stacks] == ["node", "ruby"]

    def test_go_and_rust_both_detected_in_precedence_order(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("module example\n")
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "x"\n')
        stacks = detect_stacks(tmp_path)
        assert [set_name for _label, set_name, _checks in stacks] == ["go", "rust"]

    def test_all_four_stacks_detected_together(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("module example\n")
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        (tmp_path / "package.json").write_text('{"name": "x"}\n')
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "x"\n')
        stacks = detect_stacks(tmp_path)
        assert [set_name for _label, set_name, _checks in stacks] == [
            "go", "python", "node", "rust",
        ]
