# test_checks_upgrade.py — Hermetic tests for reusable check sets + opt-in shell checks.
# Exercises: Check model validation (command/shell), the Verifier shell path,
# resolve_checks concatenation, the Policy Gate (has-checks + check-set-exists),
# and execute_mandate consuming resolved checks. All tests avoid real models.
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from alc.intake import resolve_checks
from alc.models import Blueprint, Check, Manifest
from alc.policy import lint
from alc.runner import execute_mandate
from alc.verifier import Verifier


def _manifest(check_sets: dict | None = None) -> Manifest:
    """Minimal conformant Manifest, optionally with reusable check sets."""
    return Manifest(
        version=1,
        default_engine="mock",
        compute_tiers={"standard": {"mock": "mock-small"}},
        engines={"mock": {"type": "mock"}},
        check_sets=check_sets or {},
    )


# ---------------------------------------------------------------------------
# Check model: exactly one of command / shell
# ---------------------------------------------------------------------------


class TestCheckModelValidation:
    """A Check must declare exactly one of command / shell."""

    def test_both_command_and_shell_raises(self) -> None:
        with pytest.raises(ValidationError, match="exactly one"):
            Check(name="both", command=["true"], shell="exit 0")

    def test_neither_command_nor_shell_raises(self) -> None:
        with pytest.raises(ValidationError, match="exactly one"):
            Check(name="neither")

    def test_command_only_is_valid(self) -> None:
        check = Check(name="cmd", command=["true"])
        assert check.command == ["true"]
        assert check.shell is None

    def test_shell_only_is_valid(self) -> None:
        check = Check(name="sh", shell="exit 0")
        assert check.shell == "exit 0"
        assert check.command is None


# ---------------------------------------------------------------------------
# Verifier: shell checks pass/fail by exit code
# ---------------------------------------------------------------------------


class TestVerifierShellChecks:
    """The Verifier runs shell checks via sh -c and reports pass/fail by exit code."""

    def test_shell_exit_zero_passes(self, tmp_path: Path) -> None:
        results = Verifier().run([Check(name="ok", shell="exit 0")], tmp_path)
        assert len(results) == 1
        assert results[0].passed is True

    def test_shell_exit_one_fails(self, tmp_path: Path) -> None:
        results = Verifier().run([Check(name="bad", shell="exit 1")], tmp_path)
        assert results[0].passed is False

    def test_shell_lint_style_gate(self, tmp_path: Path) -> None:
        # A real-world shape: pass when a computed value is empty.
        passing = Verifier().run([Check(name="clean", shell='test -z "$(echo)"')], tmp_path)
        assert passing[0].passed is True
        failing = Verifier().run(
            [Check(name="dirty", shell='test -z "$(echo changed)"')], tmp_path
        )
        assert failing[0].passed is False


# ---------------------------------------------------------------------------
# resolve_checks: set-then-blueprint concatenation
# ---------------------------------------------------------------------------


class TestResolveChecks:
    """resolve_checks prepends the named set's checks to the Blueprint's own."""

    def test_set_then_blueprint_order(self) -> None:
        manifest = _manifest(
            check_sets={"py": [Check(name="lint", command=["ruff", "check"])]}
        )
        blueprint = Blueprint(
            name="bp",
            purpose="p",
            checks=[Check(name="own", command=["pytest"])],
            check_set="py",
            workflow="# w",
        )
        resolved = resolve_checks(manifest, blueprint)
        assert [c.name for c in resolved] == ["lint", "own"]

    def test_no_check_set_returns_only_own(self) -> None:
        manifest = _manifest(check_sets={"py": [Check(name="lint", command=["ruff"])]})
        blueprint = Blueprint(
            name="bp",
            purpose="p",
            checks=[Check(name="own", command=["pytest"])],
            workflow="# w",
        )
        assert [c.name for c in resolve_checks(manifest, blueprint)] == ["own"]

    def test_only_check_set_no_own_checks(self) -> None:
        manifest = _manifest(check_sets={"py": [Check(name="lint", command=["ruff"])]})
        blueprint = Blueprint(
            name="bp", purpose="p", check_set="py", workflow="# w"
        )
        assert [c.name for c in resolve_checks(manifest, blueprint)] == ["lint"]


# ---------------------------------------------------------------------------
# Policy Gate: has-checks counts resolved checks; check-set-exists
# ---------------------------------------------------------------------------


class TestPolicyCheckSets:
    """The Policy Gate honours resolved checks and validates check_set names."""

    def test_blueprint_with_only_check_set_passes_has_checks(self) -> None:
        manifest = _manifest(check_sets={"py": [Check(name="test", command=["pytest"])]})
        blueprint = Blueprint(
            name="bp", purpose="p", check_set="py", workflow="# w"
        )
        violations = lint(manifest, [blueprint])
        assert not any(v.rule == "blueprint_has_checks" for v in violations)

    def test_unknown_check_set_is_error(self) -> None:
        manifest = _manifest(check_sets={})
        blueprint = Blueprint(
            name="bp", purpose="p", check_set="missing", workflow="# w"
        )
        violations = lint(manifest, [blueprint])
        matching = [v for v in violations if v.rule == "blueprint-check-set-exists"]
        assert len(matching) == 1
        assert matching[0].severity == "error"
        assert "missing" in matching[0].message

    def test_known_check_set_no_check_set_violation(self) -> None:
        manifest = _manifest(check_sets={"py": [Check(name="test", command=["pytest"])]})
        blueprint = Blueprint(
            name="bp", purpose="p", check_set="py", workflow="# w"
        )
        violations = lint(manifest, [blueprint])
        assert not any(v.rule == "blueprint-check-set-exists" for v in violations)


# ---------------------------------------------------------------------------
# execute_mandate consumes resolved checks (check_set drives success/failure)
# ---------------------------------------------------------------------------


class TestExecuteMandateResolvedChecks:
    """execute_mandate runs the check_set's checks even with no Blueprint-own checks."""

    def _run(self, command: list[str], tmp_path: Path):
        manifest = _manifest(
            check_sets={"gate": [Check(name="gate", command=command)]}
        )
        blueprint = Blueprint(
            name="bp", purpose="p", check_set="gate", workflow="# w"
        )
        return execute_mandate(
            manifest=manifest,
            blueprint=blueprint,
            directive="# Single-Mandate test\nDo nothing.",
            workdir=tmp_path,
        )

    def test_passing_check_set_succeeds(self, tmp_path: Path) -> None:
        report = self._run(["true"], tmp_path)
        assert report.success is True

    def test_failing_check_set_fails(self, tmp_path: Path) -> None:
        report = self._run(["false"], tmp_path)
        assert report.success is False


# ---------------------------------------------------------------------------
# Manifest / Blueprint front-matter round-trip for check_sets + shell checks
# ---------------------------------------------------------------------------


class TestManifestCheckSets:
    """Manifest parses check_sets, including shell-form checks."""

    def test_manifest_parses_shell_check_set(self) -> None:
        manifest = Manifest.model_validate(
            {
                "version": 1,
                "default_engine": "mock",
                "compute_tiers": {"standard": {"mock": "mock-small"}},
                "engines": {"mock": {"type": "mock"}},
                "check_sets": {
                    "py": [{"name": "clean", "shell": 'test -z "$(echo)"'}]
                },
            }
        )
        assert manifest.check_sets["py"][0].shell == 'test -z "$(echo)"'
