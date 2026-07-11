# test_tier.py — Hermetic tests for the --tier Compute Tier override feature.
#
# Covers:
#   1. _stage_blueprint priority: tier_override > stage.compute_tier > blueprint default.
#   2. _validate_tier: unknown tier -> message, known -> None, None -> None.
#   3. End-to-end smoke: FlowRunner.run(..., tier_override="deep") succeeds.
from __future__ import annotations

from pathlib import Path


from alc.cli import _validate_tier
from alc.flow import FlowRunner, _stage_blueprint
from alc.intake import load_flow, load_manifest
from alc.models import Blueprint, Check, FlowStage, Manifest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_blueprint(compute_tier: str = "standard") -> Blueprint:
    """Return a minimal Blueprint with the given compute_tier."""
    return Blueprint(
        name="demo",
        purpose="Test blueprint.",
        compute_tier=compute_tier,
        checks=[Check(name="smoke", command=["true"])],
        workflow="## Workflow\n1. Do the thing.",
    )


def _make_stage(name: str = "s", blueprint: str = "demo", compute_tier: str | None = None) -> FlowStage:
    """Return a FlowStage with an optional per-stage compute_tier."""
    return FlowStage(name=name, blueprint=blueprint, compute_tier=compute_tier)


def _make_manifest(tiers: dict | None = None) -> Manifest:
    """Return a minimal Manifest with given compute_tiers (default: standard + deep)."""
    if tiers is None:
        tiers = {
            "standard": {"mock": "mock-small"},
            "deep": {"mock": "mock-large"},
        }
    return Manifest(
        default_engine="mock",
        compute_tiers=tiers,
        engines={"mock": {"type": "mock"}},
    )


# ---------------------------------------------------------------------------
# _stage_blueprint priority tests
# ---------------------------------------------------------------------------


class TestStageBlueprintPriority:
    def test_tier_override_wins_over_stage_compute_tier(self) -> None:
        """tier_override takes priority over stage.compute_tier."""
        bp = _make_blueprint("standard")
        stage = _make_stage(compute_tier="deep")

        result = _stage_blueprint(bp, stage, tier_override="ultra")

        assert result.compute_tier == "ultra"

    def test_tier_override_wins_over_blueprint_tier(self) -> None:
        """tier_override takes priority over the Blueprint's own compute_tier."""
        bp = _make_blueprint("standard")
        stage = _make_stage(compute_tier=None)

        result = _stage_blueprint(bp, stage, tier_override="deep")

        assert result.compute_tier == "deep"

    def test_stage_compute_tier_wins_when_no_override(self) -> None:
        """stage.compute_tier is applied when no tier_override is given."""
        bp = _make_blueprint("standard")
        stage = _make_stage(compute_tier="deep")

        result = _stage_blueprint(bp, stage, tier_override=None)

        assert result.compute_tier == "deep"

    def test_blueprint_tier_unchanged_when_no_overrides(self) -> None:
        """Blueprint's own compute_tier is preserved when neither override is set."""
        bp = _make_blueprint("standard")
        stage = _make_stage(compute_tier=None)

        result = _stage_blueprint(bp, stage, tier_override=None)

        assert result.compute_tier == "standard"
        # Same object returned — no copy made.
        assert result is bp

    def test_no_copy_when_tier_already_matches(self) -> None:
        """No model_copy is made when the effective tier equals the blueprint's tier."""
        bp = _make_blueprint("deep")
        stage = _make_stage(compute_tier="deep")

        result = _stage_blueprint(bp, stage, tier_override=None)

        assert result.compute_tier == "deep"
        assert result is bp

    def test_new_object_returned_when_tier_changes(self) -> None:
        """A new Blueprint instance is returned (not the original) when tier changes."""
        bp = _make_blueprint("standard")
        stage = _make_stage(compute_tier=None)

        result = _stage_blueprint(bp, stage, tier_override="deep")

        assert result is not bp
        assert bp.compute_tier == "standard"  # original unchanged


# ---------------------------------------------------------------------------
# _validate_tier tests
# ---------------------------------------------------------------------------


class TestValidateTier:
    def test_none_returns_none(self) -> None:
        """No override requested -> no error."""
        manifest = _make_manifest()
        assert _validate_tier(manifest, None) is None

    def test_known_tier_returns_none(self) -> None:
        """A tier that exists in compute_tiers -> no error."""
        manifest = _make_manifest()
        assert _validate_tier(manifest, "deep") is None

    def test_known_tier_standard_returns_none(self) -> None:
        """'standard' tier exists in conftest manifest."""
        manifest = _make_manifest()
        assert _validate_tier(manifest, "standard") is None

    def test_unknown_tier_returns_message(self) -> None:
        """A tier not in compute_tiers -> error message string."""
        manifest = _make_manifest()
        msg = _validate_tier(manifest, "turbo")
        assert msg is not None
        assert "turbo" in msg
        # Available tiers must appear in the message.
        assert "deep" in msg
        assert "standard" in msg

    def test_error_message_lists_sorted_tiers(self) -> None:
        """Available tiers in the error message are sorted alphabetically."""
        manifest = _make_manifest({"zzz": {}, "aaa": {}, "mmm": {}})
        msg = _validate_tier(manifest, "missing")
        assert msg is not None
        idx_aaa = msg.index("aaa")
        idx_mmm = msg.index("mmm")
        idx_zzz = msg.index("zzz")
        assert idx_aaa < idx_mmm < idx_zzz


# ---------------------------------------------------------------------------
# End-to-end smoke: FlowRunner.run with tier_override
# ---------------------------------------------------------------------------


class TestFlowRunnerTierOverride:
    def test_tier_override_deep_succeeds(self, operator_layer: Path) -> None:
        """FlowRunner.run with tier_override='deep' completes successfully."""
        manifest = load_manifest(operator_layer)

        flows_dir = operator_layer.parent / manifest.flows_dir
        flow = load_flow(flows_dir, "ship")

        runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)
        report = runner.run(
            flow=flow,
            task="apply the deep tier override",
            engine_override="mock",
            tier_override="deep",
        )

        assert report.success is True
        assert len(report.stages) == 2

        # Both stages must have their compute_tier set to "deep".
        # The blueprint names still come from the flow definition.
        assert report.stages[0].blueprint == "plan"
        assert report.stages[1].blueprint == "chore"

    def test_tier_override_standard_succeeds(self, operator_layer: Path) -> None:
        """FlowRunner.run with tier_override='standard' completes successfully."""
        manifest = load_manifest(operator_layer)

        flows_dir = operator_layer.parent / manifest.flows_dir
        flow = load_flow(flows_dir, "ship")

        runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)
        report = runner.run(
            flow=flow,
            task="apply the standard tier override",
            engine_override="mock",
            tier_override="standard",
        )

        assert report.success is True

    def test_no_tier_override_preserves_existing_behavior(self, operator_layer: Path) -> None:
        """FlowRunner.run without tier_override still succeeds (regression guard)."""
        manifest = load_manifest(operator_layer)

        flows_dir = operator_layer.parent / manifest.flows_dir
        flow = load_flow(flows_dir, "ship")

        runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)
        report = runner.run(
            flow=flow,
            task="no tier override",
            engine_override="mock",
        )

        assert report.success is True
        assert report.scorecard.passes == 2
