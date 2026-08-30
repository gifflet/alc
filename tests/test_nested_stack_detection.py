"""Checks that cover half a repo are not checks.

`_marker_present` tests the project root only, so a repo keeping its frontend in
`ui/` — the common monorepo shape — got a check battery for the root stack alone
while the tool went on to promise it runs "this project's own checks". On the alc
repo itself that meant 603 frontend tests were invisible to a setup `alc lint`
then called conformant.
"""

from __future__ import annotations

from pathlib import Path

from alc.scaffold import _MAX_NESTED_STACKS, detect_nested_stacks, render_nested_check_set


def _node(d: Path) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / "package.json").write_text("{}")
    return d


def test_a_stack_one_level_down_is_found(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='r'\nversion='0'\n")
    _node(tmp_path / "ui")

    found = detect_nested_stacks(tmp_path)
    assert [(sub, label) for sub, label, _s, _c in found] == [("ui", "Node")]


def test_several_are_found_in_directory_order(tmp_path: Path) -> None:
    for name in ("ui", "docs-site", "api"):
        _node(tmp_path / name)
    assert [s for s, _l, _n, _c in detect_nested_stacks(tmp_path)] == ["api", "docs-site", "ui"]


def test_vendored_and_build_directories_are_skipped(tmp_path: Path) -> None:
    # Without this the walk finds someone else's package.json and scaffolds a
    # check for code the project does not own.
    for name in ("node_modules", "dist", "build", "vendor", "coverage"):
        _node(tmp_path / name)
    assert detect_nested_stacks(tmp_path) == []


def test_hidden_directories_are_skipped(tmp_path: Path) -> None:
    _node(tmp_path / ".cache")
    assert detect_nested_stacks(tmp_path) == []


def test_the_walk_is_capped(tmp_path: Path) -> None:
    # A monorepo can hold dozens of packages; a check per package would bury the
    # manifest and make every run pay for all of them.
    for i in range(_MAX_NESTED_STACKS + 4):
        _node(tmp_path / f"pkg{i:02d}")
    assert len(detect_nested_stacks(tmp_path)) == _MAX_NESTED_STACKS


def test_it_does_not_descend_two_levels(tmp_path: Path) -> None:
    # Depth 1 is the deliberate bound: covering ui/ and api/ without walking a
    # tree whose size nobody limited.
    _node(tmp_path / "packages" / "web")
    assert detect_nested_stacks(tmp_path) == []


def test_a_flat_project_finds_nothing(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='r'\nversion='0'\n")
    assert detect_nested_stacks(tmp_path) == []


def test_the_rendered_set_is_commented_out(tmp_path: Path) -> None:
    # Same rule this file already applies to an off-PATH binary: a live check
    # that fails on a clean checkout breaks every run, and `cd ui && npm test`
    # needs an install in that directory.
    block = render_nested_check_set("ui", "Node", [("test", ["npm", "test"])])
    assert all(line.strip().startswith("#") for line in block.splitlines() if line.strip())


def test_the_rendered_set_names_the_gap_and_the_way_out(tmp_path: Path) -> None:
    block = render_nested_check_set("ui", "Node", [("test", ["npm", "test"])])
    assert "NOT covered by the checks above" in block
    assert "Uncomment once `ui` has its dependencies installed" in block


def test_it_uses_shell_because_check_has_no_working_directory(tmp_path: Path) -> None:
    block = render_nested_check_set("ui", "Node", [("test", ["npm", "test"])])
    assert 'shell: "cd ui && npm test"' in block
    assert "command:" not in block
