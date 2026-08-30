"""A scaffolded check must be able to pass where the tool tells you to run it.

`alc init` wrote `uv run pytest -q`. In an isolated worktree that builds a fresh
venv from base dependencies alone, so a project whose tests need an extra failed
there — every time, for a reason unrelated to the change under test. The repair
turns then spend real model time chasing it.

`worktree_provision` already existed and deliberately skipped Python: at large,
Python has no single always-gitignored env dir. But once the check has been
rewritten as `uv run`, the project demonstrably uses uv, whose env is `.venv`.
"""

from __future__ import annotations

from pathlib import Path

from alc.scaffold import _render_worktree_provision_block, detect_stacks

PY_STACK = [("Python", "python", [("test", ["pytest", "-q"])])]
NODE_STACK = [("Node", "node", [("test", ["npm", "test"])])]


def _uv_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "d"\nversion = "0"\n')
    (tmp_path / "uv.lock").write_text('version = 1\n')
    return tmp_path


def test_a_uv_project_gets_its_venv_provisioned(tmp_path: Path) -> None:
    block = _render_worktree_provision_block(PY_STACK, _uv_project(tmp_path))
    assert "- clone: .venv" in block


def test_it_is_cloned_not_linked(tmp_path: Path) -> None:
    # link is shared across worktrees and safe only for read-only paths; `uv run`
    # may sync the env it is handed, and a mutation would corrupt siblings.
    block = _render_worktree_provision_block(PY_STACK, _uv_project(tmp_path))
    assert "- link: .venv" not in block


def test_no_refresh_is_scaffolded_for_it(tmp_path: Path) -> None:
    # The Node analogue would be `uv sync`, which drops extras — stripping the
    # very packages the clone carried and reintroducing the failure this fixes.
    block = _render_worktree_provision_block(PY_STACK, _uv_project(tmp_path))
    venv_line = block.index("- clone: .venv")
    assert "refresh" not in block[venv_line:]


def test_a_python_project_without_uv_gets_nothing(tmp_path: Path) -> None:
    # poetry and pipenv put their env outside the project by default. Scaffolding
    # a path that will never exist would be a silent no-op and a misleading entry.
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "d"\nversion = "0"\n')
    assert _render_worktree_provision_block(PY_STACK, tmp_path) == ""


def test_node_is_untouched(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}")
    block = _render_worktree_provision_block(NODE_STACK, tmp_path)
    assert "- link: node_modules" in block
    assert "refresh: [npm, install]" in block
    assert ".venv" not in block


def test_a_polyglot_project_gets_both(tmp_path: Path) -> None:
    _uv_project(tmp_path)
    (tmp_path / "package.json").write_text("{}")
    block = _render_worktree_provision_block(PY_STACK + NODE_STACK, tmp_path)
    assert "- link: node_modules" in block
    assert "- clone: .venv" in block


def test_the_block_stays_empty_when_nothing_applies(tmp_path: Path) -> None:
    assert _render_worktree_provision_block([("Go", "go", [])], tmp_path) == ""


def test_detect_stacks_still_sees_the_uv_project(tmp_path: Path) -> None:
    # Guards the assumption the block is keyed on: a uv project IS a python stack.
    assert any(s[1] == "python" for s in detect_stacks(_uv_project(tmp_path)))
