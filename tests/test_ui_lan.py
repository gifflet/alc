"""`alc ui --lan` — reachable from another device, and honest about the address.

Binding 0.0.0.0 is easy; the part that matters is printing something a person
can type on the phone in their hand. `http://0.0.0.0:8642` is not that.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from alc import cli as cli_mod


def _args(**over) -> argparse.Namespace:
    base = dict(host="127.0.0.1", lan=False, port=8642, ui_dist=None, no_ui=True, token=None)
    base.update(over)
    return argparse.Namespace(**base)


@pytest.fixture
def served(monkeypatch, tmp_path):
    """Run cmd_ui without actually serving; capture what uvicorn was asked to bind.

    The registry path AND the cwd are both isolated here, because cmd_ui
    registers the project it finds above the cwd into the SHARED
    ~/.alc/ui/projects.json. Without this, every `pytest` run inside an
    isolated worktree registered that worktree as a project — the operator's
    switcher grew one dead temp-dir ghost per drained task (seven of them, in
    the dogfood round that caught it).
    """
    seen: dict = {}

    def fake_run(app, host, port):
        seen["host"] = host
        seen["port"] = port

    monkeypatch.setattr("uvicorn.run", fake_run)
    monkeypatch.setattr("alc.ui.server.create_app", lambda *a, **k: object())
    registry = tmp_path / "projects.json"
    monkeypatch.setattr("alc.ui.registry.default_registry_path", lambda: registry)
    monkeypatch.setattr("alc.cli.default_registry_path", lambda: registry, raising=False)
    monkeypatch.chdir(tmp_path)
    return seen


def test_lan_binds_every_interface(served, capsys) -> None:
    assert cli_mod.cmd_ui(_args(lan=True)) == 0
    assert served["host"] == "0.0.0.0"  # noqa: S104


def test_lan_prints_a_typeable_address_not_the_bind(served, capsys, monkeypatch) -> None:
    monkeypatch.setattr(cli_mod, "_lan_address", lambda: "192.168.1.42")
    cli_mod.cmd_ui(_args(lan=True))
    out = capsys.readouterr().out

    assert "http://192.168.1.42:8642" in out
    # The bind address is not a destination. Printing it is the bug this fixes.
    assert "http://0.0.0.0" not in out
    # Loopback still works from this machine, so it is still offered.
    assert "http://127.0.0.1:8642" in out


def test_lan_says_so_when_there_is_no_route(served, capsys, monkeypatch) -> None:
    # Better an honest "no route" than an address that goes nowhere.
    monkeypatch.setattr(cli_mod, "_lan_address", lambda: None)
    cli_mod.cmd_ui(_args(lan=True))
    assert "no route to this machine" in capsys.readouterr().out


def test_lan_without_a_token_warns(served, capsys) -> None:
    cli_mod.cmd_ui(_args(lan=True))
    assert "[WARNING]" in capsys.readouterr().err


def test_lan_carries_the_token_into_both_urls(served, capsys, monkeypatch, tmp_path) -> None:
    # From a directory that is NOT a project: `alc ui` now lands on the project
    # you are standing in, and this test is about the token, not the landing.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli_mod, "_lan_address", lambda: "192.168.1.42")
    cli_mod.cmd_ui(_args(lan=True, token="s3cret"))
    out = capsys.readouterr().out

    assert "http://127.0.0.1:8642/?t=s3cret" in out
    assert "http://192.168.1.42:8642/?t=s3cret" in out


def test_default_is_still_loopback_and_silent(served, capsys) -> None:
    assert cli_mod.cmd_ui(_args()) == 0
    assert served["host"] == "127.0.0.1"
    assert "[WARNING]" not in capsys.readouterr().err


def test_host_and_lan_are_mutually_exclusive() -> None:
    # Asking for both is a contradiction; a silent precedence would hide it.
    parser = cli_mod._build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["ui", "--host", "0.0.0.0", "--lan"])


def test_lan_address_returns_a_string_or_none(tmp_path: Path) -> None:
    addr = cli_mod._lan_address()
    assert addr is None or isinstance(addr, str)
