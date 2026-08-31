# test_unit_discovery.py — "what can I run?" must have an answer.
#
# E2E finding 13: `alc run chore "…"` teaches ONE Blueprint name and the CLI had
# no way to learn the others — `alc status` reports queue, failures and branches,
# not Blueprints. Worse than the finding said: naming one that does not exist
# raised a bare FileNotFoundError traceback, which named the path it could not
# open and nothing a reader could act on.
from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from alc.cli import _list_units, _no_such_unit, _print_units, cmd_run

_BLUEPRINT = """\
---
name: {name}
purpose: {purpose}
compute_tier: standard
checks:
  - name: smoke
    command: ["true"]
---
# Workflow
1. Do the thing.
"""


def _blueprints(tmp_path: Path, **named: str) -> Path:
    d = tmp_path / "blueprints"
    d.mkdir(parents=True, exist_ok=True)
    for name, purpose in named.items():
        (d / f"{name}.md").write_text(_BLUEPRINT.format(name=name, purpose=purpose))
    return d


class TestListUnits:
    def test_reads_each_name_and_purpose(self, tmp_path: Path) -> None:
        d = _blueprints(tmp_path, chore="Apply a low-risk change.", bug="Diagnose and fix a bug.")

        assert _list_units(d, ".md") == [
            ("bug", "Diagnose and fix a bug."),
            ("chore", "Apply a low-risk change."),
        ]

    def test_sorted_by_name(self, tmp_path: Path) -> None:
        d = _blueprints(tmp_path, zeta="Z.", alpha="A.")

        assert [name for name, _ in _list_units(d, ".md")] == ["alpha", "zeta"]

    def test_a_description_key_works_too(self, tmp_path: Path) -> None:
        # Flows and Specialists say `description:` where Blueprints say `purpose:`.
        d = tmp_path / "flows"
        d.mkdir()
        (d / "ship.yaml").write_text("name: ship\ndescription: Plan then build.\nstages: []\n")

        assert _list_units(d, ".yaml") == [("ship", "Plan then build.")]

    def test_a_unit_without_a_purpose_still_lists(self, tmp_path: Path) -> None:
        d = tmp_path / "blueprints"
        d.mkdir()
        (d / "bare.md").write_text("---\nname: bare\n---\n")

        assert _list_units(d, ".md") == [("bare", "")]

    def test_an_unreadable_neighbour_never_breaks_discovery(self, tmp_path: Path) -> None:
        d = _blueprints(tmp_path, ok="Fine.")
        (d / "broken.md").write_bytes(b"\xff\xfe not text")

        names = [name for name, _ in _list_units(d, ".md")]
        assert names == ["broken", "ok"]

    def test_a_missing_directory_is_empty_not_an_error(self, tmp_path: Path) -> None:
        assert _list_units(tmp_path / "nope", ".md") == []


class TestPrintUnits:
    def test_names_and_purposes_are_aligned(self, tmp_path: Path, capsys) -> None:
        d = _blueprints(tmp_path, chore="Short.", feature="Longer one.")
        _print_units("blueprint", d, ".md")
        lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("  ")]

        assert lines[0].index("Short.") == lines[1].index("Longer one.")

    def test_an_empty_project_says_how_to_create_one(self, tmp_path: Path, capsys) -> None:
        _print_units("specialist", tmp_path / "none", ".yaml")

        assert "alc new specialist <name>" in capsys.readouterr().out


class TestNoSuchUnit:
    def test_it_names_what_does_exist(self, tmp_path: Path, capsys) -> None:
        d = _blueprints(tmp_path, chore="Apply a low-risk change.")

        assert _no_such_unit("blueprint", "refactor", d, ".md") == 1
        err = capsys.readouterr().err
        assert "no such blueprint: 'refactor'" in err
        assert "chore" in err

    def test_it_reports_on_stderr_not_stdout(self, tmp_path: Path, capsys) -> None:
        # `alc run --json` writes its report to stdout; an error listing there
        # would corrupt it.
        d = _blueprints(tmp_path, chore="x")
        _no_such_unit("blueprint", "nope", d, ".md")
        captured = capsys.readouterr()

        assert captured.out == ""
        assert "no such blueprint" in captured.err


def _run_ns(**over) -> argparse.Namespace:
    base = dict(
        blueprint=None, task=None, engine=None, isolate=False, tier=None,
        primer=None, bundle=False, from_bundle=None, json=False,
    )
    base.update(over)
    return argparse.Namespace(**base)


class TestBareRunAnswersTheQuestion:
    @staticmethod
    def _project(tmp_path: Path, monkeypatch) -> None:
        layer = tmp_path / ".alc"
        (layer / "blueprints").mkdir(parents=True)
        (layer / "manifest.yaml").write_text(
            "version: 1\ndefault_engine: mock\n"
            "compute_tiers:\n  standard:\n    mock: mock-small\n"
            "engines:\n  mock:\n    type: mock\n"
            "blueprints_dir: .alc/blueprints\nflows_dir: .alc/flows\n"
        )
        for name, purpose in (("chore", "Apply a low-risk change."), ("bug", "Fix a bug.")):
            (layer / "blueprints" / f"{name}.md").write_text(
                _BLUEPRINT.format(name=name, purpose=purpose)
            )
        monkeypatch.chdir(tmp_path)

    def test_bare_run_lists_the_blueprints_and_exits_zero(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        self._project(tmp_path, monkeypatch)

        assert cmd_run(_run_ns()) == 0
        out = capsys.readouterr().out
        assert "chore" in out and "bug" in out
        assert "Apply a low-risk change." in out
        assert 'alc run <blueprint> "<task>"' in out

    def test_an_unknown_blueprint_lists_them_instead_of_raising(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        self._project(tmp_path, monkeypatch)

        assert cmd_run(_run_ns(blueprint="refactor", task="x")) == 1
        err = capsys.readouterr().err
        assert "no such blueprint: 'refactor'" in err
        assert "chore" in err

    def test_a_named_blueprint_with_no_task_asks_for_one(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        self._project(tmp_path, monkeypatch)

        assert cmd_run(_run_ns(blueprint="chore")) == 1
        err = capsys.readouterr().err
        assert "needs a task" in err
        assert 'alc run chore "' in err

    def test_it_does_not_raise_filenotfound(self, tmp_path: Path, monkeypatch) -> None:
        # The old behaviour, stated as the thing that must not come back.
        self._project(tmp_path, monkeypatch)

        try:
            cmd_run(_run_ns(blueprint="refactor", task="x"))
        except FileNotFoundError:  # pragma: no cover - the regression itself
            pytest.fail("an unknown Blueprint must not raise a traceback")
