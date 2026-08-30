"""Shape and reach are different questions.

`alc lint` printed "No violations found. Operator Layer is conformant." over a
layer whose only check was pytest, in a repo where half the code is TypeScript.
Conformant is about shape; a reader takes it as sound.
"""

from __future__ import annotations

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
