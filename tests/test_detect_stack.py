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


class TestDetectStacksMulti:
    def test_python_and_node_both_detected(self, tmp_path: Path) -> None:
        """A polyglot project keeps BOTH stacks — the first-match-wins gap is fixed."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        (tmp_path / "package.json").write_text('{"name": "x"}\n')
        stacks = detect_stacks(tmp_path)
        assert [set_name for _label, set_name, _checks in stacks] == ["python", "node"]

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
