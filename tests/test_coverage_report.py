"""Shape and reach are different questions.

`alc lint` printed "No violations found. Operator Layer is conformant." over a
layer whose only check was pytest, in a repo where half the code is TypeScript.
Conformant is about shape; a reader takes it as sound.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from alc.models import Blueprint, Check, Manifest
from alc.policy import coverage_report


def _manifest(**kw) -> Manifest:
    base = dict(
        version=1,
        default_engine="mock",
        engines={"mock": {"type": "mock"}},
        compute_tiers={"standard": {"mock": "mock-small"}},
    )
    base.update(kw)
    return Manifest(**base)


def _bp(name: str, checks: list[Check], check_set: str | None = None) -> Blueprint:
    return Blueprint(
        name=name, purpose="p", workflow="w", checks=checks, check_set=check_set
    )


PYTEST = Check(name="test", command=["uv", "run", "pytest", "-q"])
GITLEAKS = Check(name="secrets", command=["gitleaks", "detect"])


def test_a_set_nothing_references_and_nothing_else_runs_is_reported(tmp_path: Path) -> None:
    m = _manifest(check_sets={"security": [GITLEAKS]})
    lines = coverage_report(m, [_bp("chore", [PYTEST])], tmp_path)
    assert any("security" in line for line in lines)


def test_a_set_whose_checks_already_run_inline_is_not_reported(tmp_path: Path) -> None:
    # `alc init` writes a `python` set holding the very check the scaffolded
    # Blueprints declare inline. It is a reusable pool, not a hole — flagging it
    # would fire on every project alc has ever created, and an alarm that always
    # fires is one nobody reads.
    m = _manifest(check_sets={"python": [PYTEST]})
    assert coverage_report(m, [_bp("chore", [PYTEST])], tmp_path) == []


def test_an_empty_set_is_not_reported(tmp_path: Path) -> None:
    # Its checks were commented out for an off-PATH binary; there is nothing to
    # claim about a set that declares nothing.
    m = _manifest(check_sets={"security": []})
    assert coverage_report(m, [_bp("chore", [PYTEST])], tmp_path) == []


def test_a_referenced_set_is_not_reported(tmp_path: Path) -> None:
    m = _manifest(check_sets={"security": [GITLEAKS]})
    lines = coverage_report(m, [_bp("chore", [PYTEST], check_set="security")], tmp_path)
    assert lines == []


def test_a_nested_stack_no_check_mentions_is_reported(tmp_path: Path) -> None:
    (tmp_path / "ui").mkdir()
    (tmp_path / "ui" / "package.json").write_text("{}")
    lines = coverage_report(_manifest(), [_bp("chore", [PYTEST])], tmp_path)
    assert any("Node in ui/" in line for line in lines)


def test_a_nested_stack_a_check_does_mention_is_not_reported(tmp_path: Path) -> None:
    (tmp_path / "ui").mkdir()
    (tmp_path / "ui" / "package.json").write_text("{}")
    ui_check = Check(name="ui-test", shell="cd ui && npm test")
    assert coverage_report(_manifest(), [_bp("chore", [ui_check])], tmp_path) == []


def test_a_set_reaches_a_stack_only_when_a_blueprint_wires_it(tmp_path: Path) -> None:
    # The correction that mattered: uncommenting a check_set declares it and
    # nothing more. resolve_checks is the set PLUS the Blueprint's own, so a
    # Blueprint with no `check_set:` never reaches it.
    (tmp_path / "ui").mkdir()
    (tmp_path / "ui" / "package.json").write_text("{}")
    ui_check = Check(name="ui-test", shell="cd ui && npm test")
    m = _manifest(check_sets={"ui": [ui_check]})

    unwired = coverage_report(m, [_bp("chore", [PYTEST])], tmp_path)
    assert any("Node in ui/" in line for line in unwired)

    wired = coverage_report(m, [_bp("chore", [PYTEST], check_set="ui")], tmp_path)
    assert not any("Node in ui/" in line for line in wired)


def test_a_fully_covered_flat_project_says_nothing(tmp_path: Path) -> None:
    assert coverage_report(_manifest(), [_bp("chore", [PYTEST])], tmp_path) == []


class TestLintHumanOutput:
    """The pure `coverage_report` was covered; the sentence an operator reads
    was not. A3 taught the difference: a layer can be well-formed and still
    reach none of the project, and only the CLI string says so."""

    @staticmethod
    def _project(tmp_path: Path, monkeypatch, *, nested: bool) -> None:
        layer = tmp_path / ".alc"
        (layer / "blueprints").mkdir(parents=True)
        (layer / "manifest.yaml").write_text(
            "version: 1\ndefault_engine: mock\n"
            "compute_tiers:\n  standard:\n    mock: mock-small\n"
            "engines:\n  mock:\n    type: mock\n"
            "check_sets:\n  python:\n    - name: test\n      command: [\"pytest\", \"-q\"]\n"
            "blueprints_dir: .alc/blueprints\nflows_dir: .alc/flows\n"
        )
        (layer / "blueprints" / "chore.md").write_text(
            "---\nname: chore\npurpose: Do a chore.\ncompute_tier: standard\n"
            "checks:\n  - name: test\n    command: [\"pytest\", \"-q\"]\n"
            "report:\n  format: json\n  schema:\n    status: string\n---\n# Workflow\n1. Go.\n"
        )
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.1.0"\n')
        if nested:
            (tmp_path / "ui").mkdir()
            (tmp_path / "ui" / "package.json").write_text('{"name":"ui","scripts":{"test":"x"}}')
        monkeypatch.chdir(tmp_path)

    def test_a_reachable_layer_reports_well_formed(self, tmp_path: Path, monkeypatch, capsys) -> None:
        from alc.cli import cmd_lint

        self._project(tmp_path, monkeypatch, nested=False)

        assert cmd_lint(argparse.Namespace(json=False)) == 0
        out = capsys.readouterr().out
        assert "No violations found" in out
        assert "does not reach" not in out

    def test_an_unreached_stack_is_named_not_called_conformant(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        from alc.cli import cmd_lint

        self._project(tmp_path, monkeypatch, nested=True)

        assert cmd_lint(argparse.Namespace(json=False)) == 0
        out = capsys.readouterr().out
        assert "does not reach all of this project" in out
        assert "ui/" in out

    def test_the_json_contract_stays_an_array_of_violations(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        import json as _json

        from alc.cli import cmd_lint

        self._project(tmp_path, monkeypatch, nested=True)

        assert cmd_lint(argparse.Namespace(json=True)) == 0
        assert _json.loads(capsys.readouterr().out) == []
