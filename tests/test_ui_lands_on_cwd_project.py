"""`alc ui` should open the project you are standing in.

Every other command is scoped to the cwd — `alc run`, `alc lint`, `alc team` all
act on the project you are in. `alc ui` alone read the global registry and
ignored it, so `cd my-project && alc ui` opened a list of whatever had been
registered before, and reaching the project you were in meant typing its
absolute path into a dialog.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest

from alc import cli as cli_mod


def _args(**over) -> argparse.Namespace:
    base = dict(host="127.0.0.1", lan=False, port=8642, ui_dist=None, no_ui=True, token=None)
    base.update(over)
    return argparse.Namespace(**base)


@pytest.fixture
def served(monkeypatch, tmp_path):
    """Run cmd_ui without serving, with the registry redirected into tmp_path."""
    monkeypatch.setattr("uvicorn.run", lambda app, host, port: None)
    monkeypatch.setattr("alc.ui.server.create_app", lambda *a, **k: object())
    registry = tmp_path / "registry.json"
    monkeypatch.setattr("alc.ui.registry.default_registry_path", lambda: registry)
    monkeypatch.setattr("alc.cli.default_registry_path", lambda: registry, raising=False)
    return registry


def _project(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
    monkeypatch.chdir(root)
    cli_mod.cmd_init(cli_mod._build_parser().parse_args(["init", "--engine", "mock"]))
    return root


def test_the_printed_url_points_at_the_project_you_are_in(served, tmp_path, monkeypatch, capsys) -> None:
    _project(tmp_path, monkeypatch)
    capsys.readouterr()

    cli_mod.cmd_ui(_args())
    out = capsys.readouterr().out

    assert "/projects/proj-" in out, "the Local URL must land on this project"


def test_registering_is_announced_because_it_writes_shared_state(served, tmp_path, monkeypatch, capsys) -> None:
    # The registry is one file shared by every project. Adding to it silently
    # would change persistent state as a side effect of starting a server.
    _project(tmp_path, monkeypatch)
    capsys.readouterr()

    cli_mod.cmd_ui(_args())
    assert "Registered proj" in capsys.readouterr().out


def test_it_announces_only_the_first_time(served, tmp_path, monkeypatch, capsys) -> None:
    _project(tmp_path, monkeypatch)
    cli_mod.cmd_ui(_args())
    capsys.readouterr()

    cli_mod.cmd_ui(_args())
    out = capsys.readouterr().out
    assert "Registered" not in out
    assert "/projects/proj-" in out, "but it still lands there"


def test_it_works_from_a_subdirectory(served, tmp_path, monkeypatch, capsys) -> None:
    # `alc run` works from a subdirectory; this has no business being stricter.
    root = _project(tmp_path, monkeypatch)
    deep = root / "src" / "deep"
    deep.mkdir(parents=True)
    monkeypatch.chdir(deep)
    capsys.readouterr()

    cli_mod.cmd_ui(_args())
    assert "/projects/proj-" in capsys.readouterr().out


def test_outside_a_project_nothing_changes(served, tmp_path, monkeypatch, capsys) -> None:
    empty = tmp_path / "elsewhere"
    empty.mkdir()
    monkeypatch.chdir(empty)
    capsys.readouterr()

    cli_mod.cmd_ui(_args())
    out = capsys.readouterr().out
    assert "/projects/" not in out
    assert "Registered" not in out
    assert not served.exists(), "no registry file should be created either"


def test_the_token_url_still_carries_the_token_and_the_project(served, tmp_path, monkeypatch, capsys) -> None:
    _project(tmp_path, monkeypatch)
    capsys.readouterr()

    cli_mod.cmd_ui(_args(token="s3cret"))
    out = capsys.readouterr().out
    assert "/projects/proj-" in out
    assert "?t=s3cret" in out


def test_outside_a_project_the_token_url_keeps_its_slash(served, tmp_path, monkeypatch, capsys) -> None:
    # `f"{landing}?t=…"` with an empty landing produced ":8642?t=x" — no path at
    # all. It works, and it is sloppy in the one URL a person has to retype.
    empty = tmp_path / "elsewhere"
    empty.mkdir()
    monkeypatch.chdir(empty)
    capsys.readouterr()

    cli_mod.cmd_ui(_args(token="s3cret"))
    assert "/?t=s3cret" in capsys.readouterr().out
