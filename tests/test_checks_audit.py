# test_checks_audit.py — Hermetic tests for `alc checks audit` (roadmap-phase-2.md
# T13): the pure audit_checks() function, its CLI wiring, and the advisory Policy
# Gate rule that flags an execution Blueprint resolving to only the smoke
# placeholder. audit_checks() never writes — every assertion here is read-only.
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from alc.checks import ChecksAudit, CheckSetAudit, SmokeOnlyBlueprint, audit_checks
from alc.cli import cmd_checks
from alc.models import Blueprint, Check, Manifest
from alc.policy import lint


def _manifest(check_sets: dict | None = None) -> Manifest:
    return Manifest(
        version=1,
        default_engine="mock",
        compute_tiers={"standard": {"mock": "mock-small"}},
        engines={"mock": {"type": "mock"}},
        check_sets=check_sets or {},
    )


def _blueprint(name: str = "chore", check_set: str | None = None, checks=None) -> Blueprint:
    return Blueprint(
        name=name,
        purpose="p",
        check_set=check_set,
        checks=checks if checks is not None else [Check(name="smoke", command=["true"])],
        workflow="# w",
    )


# ---------------------------------------------------------------------------
# audit_checks — check_sets: new / add / unavailable
# ---------------------------------------------------------------------------


class TestAuditChecksCheckSets:
    def test_new_stack_not_in_manifest_is_flagged_new(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("alc.checks.shutil.which", lambda cmd: f"/usr/bin/{cmd}")
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")

        report = audit_checks(_manifest(), tmp_path, [])

        python_set = next(cs for cs in report.check_sets if cs.set_name == "python")
        assert python_set.is_new is True
        assert {name for name, _cmd in python_set.add} == {"test", "lint"}
        assert python_set.unavailable == []

    def test_binary_missing_reports_unavailable_not_add(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("alc.checks.shutil.which", lambda cmd: None)
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")

        report = audit_checks(_manifest(), tmp_path, [])

        python_set = next(cs for cs in report.check_sets if cs.set_name == "python")
        assert python_set.add == []
        assert {name for name, _cmd in python_set.unavailable} == {"test", "lint"}

    def test_already_live_check_is_not_proposed_again(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("alc.checks.shutil.which", lambda cmd: f"/usr/bin/{cmd}")
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
        manifest = _manifest(
            check_sets={"python": [Check(name="test", command=["pytest", "-q"])]}
        )

        report = audit_checks(manifest, tmp_path, [])

        python_set = next(cs for cs in report.check_sets if cs.set_name == "python")
        assert python_set.is_new is False
        assert {name for name, _cmd in python_set.add} == {"lint"}  # "test" already live

    def test_fully_up_to_date_set_is_omitted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("alc.checks.shutil.which", lambda cmd: None)  # nothing installed
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
        manifest = _manifest(
            check_sets={
                "python": [
                    Check(name="test", command=["pytest", "-q"]),
                    Check(name="lint", command=["ruff", "check", "."]),
                ]
            }
        )

        report = audit_checks(manifest, tmp_path, [])

        assert not any(cs.set_name == "python" for cs in report.check_sets)

    def test_no_stack_still_audits_the_security_set(self, tmp_path: Path) -> None:
        report = audit_checks(_manifest(), tmp_path, [])
        assert any(cs.set_name == "security" for cs in report.check_sets)

    def test_no_proposals_has_proposals_is_false(self, tmp_path: Path) -> None:
        # gitleaks (the only stack-agnostic security check) unavailable, no stack:
        # still ends up with an empty ChecksAudit whenever nothing is actionable.
        report = ChecksAudit(check_sets=[], smoke_only_blueprints=[])
        assert report.has_proposals is False

    def test_unavailable_only_set_still_has_no_proposals(self) -> None:
        report = ChecksAudit(
            check_sets=[
                CheckSetAudit(
                    set_name="security", is_new=False, add=[], unavailable=[("gitleaks", ["gitleaks", "detect"])]
                )
            ],
            smoke_only_blueprints=[],
        )
        assert report.has_proposals is False

    def test_add_proposal_has_proposals_is_true(self) -> None:
        report = ChecksAudit(
            check_sets=[
                CheckSetAudit(
                    set_name="python", is_new=True, add=[("test", ["pytest", "-q"])], unavailable=[]
                )
            ],
            smoke_only_blueprints=[],
        )
        assert report.has_proposals is True


# ---------------------------------------------------------------------------
# audit_checks — smoke-only Blueprints
# ---------------------------------------------------------------------------


class TestAuditChecksSmokeOnlyBlueprints:
    def test_smoke_only_blueprint_flagged_when_stack_detected(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
        bp = _blueprint("chore")

        report = audit_checks(_manifest(), tmp_path, [bp])

        assert report.smoke_only_blueprints == [
            SmokeOnlyBlueprint(blueprint="chore", stacks=["Python"])
        ]

    def test_no_stack_detected_nothing_flagged(self, tmp_path: Path) -> None:
        bp = _blueprint("chore")
        report = audit_checks(_manifest(), tmp_path, [bp])
        assert report.smoke_only_blueprints == []

    def test_blueprint_with_real_checks_not_flagged(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
        bp = _blueprint("chore", checks=[Check(name="test", command=["pytest", "-q"])])
        report = audit_checks(_manifest(), tmp_path, [bp])
        assert report.smoke_only_blueprints == []

    def test_plan_is_never_flagged(self, tmp_path: Path) -> None:
        """`plan` keeps the smoke placeholder by design — a planning stage writes no code."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")

        report = audit_checks(_manifest(), tmp_path, [_blueprint("plan"), _blueprint("chore")])

        assert [s.blueprint for s in report.smoke_only_blueprints] == ["chore"]


# ---------------------------------------------------------------------------
# CLI — `alc checks audit [--json]`
# ---------------------------------------------------------------------------


def _ns(**overrides) -> argparse.Namespace:
    defaults = {"checks_action": "audit", "json": False}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestChecksAuditCli:
    def test_never_writes_anything(
        self, operator_layer: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)
        before = sorted(p.relative_to(operator_layer.parent) for p in operator_layer.rglob("*"))
        assert cmd_checks(_ns()) == 0
        after = sorted(p.relative_to(operator_layer.parent) for p in operator_layer.rglob("*"))
        assert before == after

    def test_security_set_always_appears_even_with_no_stack(
        self, operator_layer: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)
        assert cmd_checks(_ns()) == 0
        out = capsys.readouterr().out
        assert "security" in out  # `_build_check_sets` always includes it

    def test_json_output_matches_audit_checks(
        self, operator_layer: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        monkeypatch.chdir(operator_layer.parent)
        assert cmd_checks(_ns(json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert "check_sets" in data
        assert "smoke_only_blueprints" in data


# ---------------------------------------------------------------------------
# Policy Gate — advisory smoke-only-execution-blueprint rule (T13)
# ---------------------------------------------------------------------------


class TestSmokeOnlyPolicyRule:
    def _manifest_with_empty_set(self) -> Manifest:
        return _manifest(check_sets={"python": []})

    def test_warns_when_check_set_resolves_empty_and_own_checks_are_smoke_only(self) -> None:
        bp = _blueprint("chore", check_set="python")
        violations = lint(self._manifest_with_empty_set(), [bp])
        matching = [v for v in violations if v.rule == "blueprint-checks-smoke-only"]
        assert len(matching) == 1
        assert matching[0].severity == "warn"

    def test_no_warn_when_check_set_resolves_to_real_checks(self) -> None:
        manifest = _manifest(check_sets={"python": [Check(name="test", command=["pytest", "-q"])]})
        bp = _blueprint("chore", check_set="python")
        violations = lint(manifest, [bp])
        assert not any(v.rule == "blueprint-checks-smoke-only" for v in violations)

    def test_plan_blueprint_is_always_exempt(self) -> None:
        # Constraint: a planning stage legitimately produces no executable code.
        bp = _blueprint("plan", check_set="python")
        violations = lint(self._manifest_with_empty_set(), [bp])
        assert not any(v.rule == "blueprint-checks-smoke-only" for v in violations)

    def test_no_check_set_never_warns_even_when_smoke_only(self) -> None:
        # Constraint: the default `alc init` layer (no stack detected) writes
        # smoke-only Blueprints with NO check_set — must stay lint-clean.
        bp = _blueprint("chore", check_set=None)
        violations = lint(_manifest(), [bp])
        assert not any(v.rule == "blueprint-checks-smoke-only" for v in violations)
