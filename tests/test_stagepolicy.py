# test_stagepolicy.py — Hermetic tests for T5: `stage:`/`stage_mix:` on the
# Manifest and src/alc/stagepolicy.py. Every rule here is advisory (warn) with
# the sole exception of a malformed `stage_mix` override itself (error) — and
# a Blueprint with no `archetype` is NEVER penalised.
from __future__ import annotations

from pathlib import Path

from alc.intake import load_all_blueprints, load_manifest
from alc.models import Blueprint, Manifest
from alc.policy import has_errors
from alc.scaffold import scaffold
from alc.stagepolicy import STAGE_MIX, effective_mix, lint_stage


def _manifest(**overrides) -> Manifest:
    defaults = dict(
        version=1,
        default_engine="mock",
        compute_tiers={"standard": {"mock": "mock-small"}, "deep": {"mock": "mock-large"}},
        engines={"mock": {"type": "mock"}},
    )
    defaults.update(overrides)
    return Manifest(**defaults)


def _bp(name: str, archetype: str | None = None, compute_tier: str = "standard") -> Blueprint:
    from alc.models import Check

    return Blueprint(
        name=name,
        purpose="p",
        compute_tier=compute_tier,
        checks=[Check(name="smoke", command=["true"])],
        workflow="# w",
        archetype=archetype,
    )


# ---------------------------------------------------------------------------
# STAGE_MIX — the essay's formula as plain data
# ---------------------------------------------------------------------------


class TestStageMixData:
    def test_pre_pmf_core_is_prototyper_builder_sweeper(self) -> None:
        assert set(STAGE_MIX["pre-pmf"]["core"]) == {"prototyper", "builder", "sweeper"}
        assert STAGE_MIX["pre-pmf"]["secondary"] == []

    def test_growth_core_plus_secondary_maintainer(self) -> None:
        assert set(STAGE_MIX["growth"]["core"]) == {"builder", "sweeper", "grower"}
        assert STAGE_MIX["growth"]["secondary"] == ["maintainer"]

    def test_strong_pmf_core_plus_secondary_builder(self) -> None:
        assert set(STAGE_MIX["strong-pmf"]["core"]) == {"sweeper", "grower", "maintainer"}
        assert STAGE_MIX["strong-pmf"]["secondary"] == ["builder"]


# ---------------------------------------------------------------------------
# effective_mix — resolution + the stage_mix override escape hatch
# ---------------------------------------------------------------------------


class TestEffectiveMix:
    def test_none_when_no_stage_declared(self) -> None:
        assert effective_mix(_manifest()) is None

    def test_default_mix_when_stage_set_and_no_override(self) -> None:
        mix = effective_mix(_manifest(stage="growth"))
        assert mix == STAGE_MIX["growth"]

    def test_stage_mix_override_replaces_the_default_wholesale(self) -> None:
        override = {"core": ["maintainer"], "secondary": []}
        mix = effective_mix(_manifest(stage="growth", stage_mix=override))
        assert mix == override


# ---------------------------------------------------------------------------
# lint_stage — the opt-in invariant: a freshly-init'd project stays silent
# ---------------------------------------------------------------------------


class TestLintStageOptIn:
    def test_no_stage_no_stage_mix_yields_nothing(self) -> None:
        assert lint_stage(_manifest(), [_bp("chore")]) == []

    def test_freshly_scaffolded_project_lints_silent(self, tmp_path: Path) -> None:
        """`alc init` writes no `stage` — a rule that cries wolf on day one is a
        rule operators learn to ignore."""
        scaffold(tmp_path)
        operator_layer = tmp_path / ".alc"
        manifest = load_manifest(operator_layer)
        blueprints = load_all_blueprints(manifest, operator_layer)

        assert lint_stage(manifest, blueprints) == []


# ---------------------------------------------------------------------------
# lint_stage — rule: a stage's CORE archetype with no Blueprint declaring it
# ---------------------------------------------------------------------------


class TestLintStageCoreArchetypeMissing:
    def test_missing_core_archetype_warns_with_hire_hint(self) -> None:
        # pre-pmf core = prototyper + builder + sweeper; only builder is present.
        manifest = _manifest(stage="pre-pmf")
        blueprints = [_bp("feature", archetype="builder")]

        violations = lint_stage(manifest, blueprints)
        rules = {v.rule for v in violations}
        assert "stage-core-archetype-missing" in rules
        assert not has_errors(violations)

        messages = [v.message for v in violations if v.rule == "stage-core-archetype-missing"]
        assert any("alc team hire prototyper" in m for m in messages)
        assert any("alc team hire sweeper" in m for m in messages)

    def test_every_core_archetype_present_yields_no_missing_warning(self) -> None:
        manifest = _manifest(stage="pre-pmf")
        blueprints = [
            _bp("a", archetype="prototyper"),
            _bp("b", archetype="builder"),
            _bp("c", archetype="sweeper"),
        ]
        violations = lint_stage(manifest, blueprints)
        assert not any(v.rule == "stage-core-archetype-missing" for v in violations)

    def test_missing_secondary_archetype_never_warns(self) -> None:
        # growth secondary = maintainer; absent entirely, but that is optional.
        manifest = _manifest(stage="growth")
        blueprints = [
            _bp("a", archetype="builder"),
            _bp("b", archetype="sweeper"),
            _bp("c", archetype="grower"),
        ]
        violations = lint_stage(manifest, blueprints)
        assert violations == []


# ---------------------------------------------------------------------------
# lint_stage — rule: a `deep`-tier Blueprint whose archetype is off-mix
# ---------------------------------------------------------------------------


class TestLintStageDeepTierOffMix:
    def test_deep_tier_off_mix_archetype_warns(self) -> None:
        # strong-pmf mix = sweeper+grower+maintainer (core) + builder (secondary).
        # prototyper is off-mix entirely.
        manifest = _manifest(stage="strong-pmf")
        blueprints = [_bp("spike", archetype="prototyper", compute_tier="deep")]

        violations = lint_stage(manifest, blueprints)
        matching = [v for v in violations if v.rule == "stage-deep-tier-off-mix"]
        assert len(matching) == 1
        assert matching[0].severity == "warn"
        assert "prototyper" in matching[0].message

    def test_deep_tier_in_core_mix_does_not_warn(self) -> None:
        manifest = _manifest(stage="strong-pmf")
        blueprints = [_bp("scan", archetype="sweeper", compute_tier="deep")]

        violations = lint_stage(manifest, blueprints)
        assert not any(v.rule == "stage-deep-tier-off-mix" for v in violations)

    def test_deep_tier_in_secondary_mix_does_not_warn(self) -> None:
        # strong-pmf secondary = builder.
        manifest = _manifest(stage="strong-pmf")
        blueprints = [_bp("feature", archetype="builder", compute_tier="deep")]

        violations = lint_stage(manifest, blueprints)
        assert not any(v.rule == "stage-deep-tier-off-mix" for v in violations)

    def test_standard_tier_off_mix_archetype_does_not_warn(self) -> None:
        """Only `deep` tier triggers this rule — a cheap tier off-mix is not flagged."""
        manifest = _manifest(stage="strong-pmf")
        blueprints = [_bp("spike", archetype="prototyper", compute_tier="standard")]

        violations = lint_stage(manifest, blueprints)
        assert not any(v.rule == "stage-deep-tier-off-mix" for v in violations)

    def test_no_archetype_is_never_penalised_even_at_deep_tier_off_mix(self) -> None:
        manifest = _manifest(stage="strong-pmf")
        blueprints = [_bp("mystery", archetype=None, compute_tier="deep")]

        violations = lint_stage(manifest, blueprints)
        # No archetype -> this rule NEVER fires for this Blueprint (other rules,
        # like the unrelated "core archetype missing", are free to fire).
        assert not any(v.rule == "stage-deep-tier-off-mix" for v in violations)


# ---------------------------------------------------------------------------
# lint_stage — stage_mix override validation (the escape hatch itself)
# ---------------------------------------------------------------------------


class TestLintStageMixOverrideValidation:
    def test_unknown_top_level_key_is_an_error(self) -> None:
        manifest = _manifest(stage="growth", stage_mix={"tertiary": ["builder"]})
        violations = lint_stage(manifest, [])
        matching = [v for v in violations if v.rule == "stage-mix-shape"]
        assert len(matching) == 1
        assert matching[0].severity == "error"

    def test_unknown_archetype_name_is_an_error(self) -> None:
        manifest = _manifest(stage="growth", stage_mix={"core": ["not-a-real-archetype"]})
        violations = lint_stage(manifest, [])
        matching = [v for v in violations if v.rule == "stage-mix-archetype-known"]
        assert len(matching) == 1
        assert matching[0].severity == "error"
        assert "not-a-real-archetype" in matching[0].message

    def test_well_formed_override_yields_no_shape_errors(self) -> None:
        manifest = _manifest(
            stage="growth", stage_mix={"core": ["maintainer"], "secondary": ["builder"]}
        )
        violations = lint_stage(manifest, [_bp("a", archetype="maintainer")])
        assert not has_errors(violations)

    def test_override_changes_which_archetype_is_core(self) -> None:
        # Override growth's core down to just "maintainer" — builder/sweeper/grower
        # (the DEFAULT core) must no longer be required.
        manifest = _manifest(
            stage="growth", stage_mix={"core": ["maintainer"], "secondary": []}
        )
        violations = lint_stage(manifest, [])
        missing = [v for v in violations if v.rule == "stage-core-archetype-missing"]
        assert [v.message for v in missing] and "maintainer" in missing[0].message
        assert len(missing) == 1  # only maintainer, not the default core trio

    def test_stage_mix_set_without_stage_still_validates_shape(self) -> None:
        """Structural validation runs regardless of `stage` — but no mix-comparison
        rule can fire without a declared stage to compare against."""
        manifest = _manifest(stage=None, stage_mix={"bogus": []})
        violations = lint_stage(manifest, [])
        assert [v.rule for v in violations] == ["stage-mix-shape"]
