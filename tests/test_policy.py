# test_policy.py — Tests for the Policy Gate (policy.py).
from __future__ import annotations

import pytest

from alc.models import Blueprint, Check, Manifest, ReportSpec
from alc.policy import Violation, has_errors, lint


def _valid_manifest() -> Manifest:
    return Manifest(
        version=1,
        default_engine="mock",
        compute_tiers={"standard": {"mock": "mock-small"}},
        engines={"mock": {"type": "mock"}},
        blueprints_dir=".alc/blueprints",
    )


def _valid_blueprint() -> Blueprint:
    return Blueprint(
        name="chore",
        purpose="Apply a small housekeeping change.",
        compute_tier="standard",
        checks=[Check(name="smoke", command=["true"])],
        report=ReportSpec(format="json", schema={}),
        workflow="## Workflow\n\nDo the thing.",
    )


class TestPolicyLint:
    def test_valid_manifest_and_blueprint_yields_no_errors(self) -> None:
        manifest = _valid_manifest()
        blueprint = _valid_blueprint()
        violations = lint(manifest, [blueprint])
        assert not has_errors(violations), f"Unexpected errors: {violations}"

    def test_blueprint_with_zero_checks_yields_error(self) -> None:
        manifest = _valid_manifest()
        blueprint = Blueprint(
            name="chore",
            purpose="Some purpose.",
            compute_tier="standard",
            checks=[],  # <-- no checks
            report=ReportSpec(format="json", schema={}),
            workflow="## Workflow",
        )
        violations = lint(manifest, [blueprint])
        assert has_errors(violations)
        error_rules = [v.rule for v in violations if v.severity == "error"]
        assert "blueprint_has_checks" in error_rules

    def test_missing_default_engine_yields_error(self) -> None:
        manifest = Manifest(
            version=1,
            default_engine="nonexistent",
            compute_tiers={"standard": {"mock": "mock-small"}},
            engines={"mock": {"type": "mock"}},
        )
        blueprint = _valid_blueprint()
        violations = lint(manifest, [blueprint])
        assert has_errors(violations)
        assert any(v.rule == "default_engine_resolvable" for v in violations)

    def test_blueprint_without_report_yields_warn_not_error(self) -> None:
        manifest = _valid_manifest()
        blueprint = Blueprint(
            name="chore",
            purpose="Some purpose.",
            compute_tier="standard",
            checks=[Check(name="smoke", command=["true"])],
            report=None,  # <-- no report spec
            workflow="## Workflow",
        )
        violations = lint(manifest, [blueprint])
        # Should have a warn, but no error.
        assert not has_errors(violations)
        warn_rules = [v.rule for v in violations if v.severity == "warn"]
        assert "blueprint_has_report" in warn_rules

    def test_compute_tier_missing_engine_yields_error(self) -> None:
        manifest = Manifest(
            version=1,
            default_engine="mock",
            compute_tiers={"standard": {"claude-code": "claude-sonnet-4-6"}},  # mock missing
            engines={"mock": {"type": "mock"}},
        )
        blueprint = _valid_blueprint()
        violations = lint(manifest, [blueprint])
        assert has_errors(violations)
        assert any(v.rule == "compute_tier_maps_engine" for v in violations)


# ---------------------------------------------------------------------------
# validate_prompts — reserved override placeholders + {{prompt:X}} references
# ---------------------------------------------------------------------------


class TestValidatePrompts:
    def _blueprint_with_workflow(self, workflow: str) -> Blueprint:
        return Blueprint(
            name="chore",
            purpose="Apply a small housekeeping change.",
            compute_tier="standard",
            checks=[Check(name="smoke", command=["true"])],
            report=ReportSpec(format="json", schema={}),
            workflow=workflow,
        )

    def test_clean_setup_has_no_violations(self, operator_layer) -> None:
        from alc.intake import load_all_blueprints
        from alc.policy import validate_prompts

        manifest = load_manifest_from(operator_layer)
        blueprints = load_all_blueprints(manifest, operator_layer)
        assert validate_prompts(manifest, operator_layer, blueprints) == []

    def test_override_missing_placeholder_flagged(self, operator_layer) -> None:
        from alc.policy import validate_prompts

        manifest = load_manifest_from(operator_layer)
        prompts_dir = operator_layer / "prompts"
        prompts_dir.mkdir(exist_ok=True)
        # conductor override missing {catalog_text}.
        (prompts_dir / "conductor.md").write_text("only has {goal}")

        violations = validate_prompts(manifest, operator_layer, [])
        assert has_errors(violations)
        assert any(v.rule == "prompt-override-placeholders" for v in violations)

    def test_override_stray_brace_flagged(self, operator_layer) -> None:
        from alc.policy import validate_prompts

        manifest = load_manifest_from(operator_layer)
        prompts_dir = operator_layer / "prompts"
        prompts_dir.mkdir(exist_ok=True)
        # Has both placeholders but a stray unescaped {oops} that would crash .format().
        (prompts_dir / "conductor.md").write_text("{goal} {catalog_text} then {oops}")

        violations = validate_prompts(manifest, operator_layer, [])
        assert has_errors(violations)
        assert any(v.rule == "prompt-override-formattable" for v in violations)

    def test_dangling_include_flagged(self, operator_layer) -> None:
        from alc.policy import validate_prompts

        manifest = load_manifest_from(operator_layer)
        bp = self._blueprint_with_workflow("Do it. {{prompt:nonexistent}}")
        violations = validate_prompts(manifest, operator_layer, [bp])
        assert has_errors(violations)
        assert any(v.rule == "prompt-include-resolves" for v in violations)

    def test_resolvable_include_ok(self, operator_layer) -> None:
        from alc.policy import validate_prompts

        manifest = load_manifest_from(operator_layer)
        prompts_dir = operator_layer / "prompts"
        prompts_dir.mkdir(exist_ok=True)
        (prompts_dir / "helper.md").write_text("HELPER TEXT")

        bp = self._blueprint_with_workflow("Do it. {{prompt:helper}}")
        violations = validate_prompts(manifest, operator_layer, [bp])
        assert not has_errors(violations)


def load_manifest_from(operator_layer):
    """Load the Manifest from an on-disk Operator Layer fixture."""
    from alc.intake import load_manifest

    return load_manifest(operator_layer)
