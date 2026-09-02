# test_pack_grower.py — Hermetic tests for the Grower Archetype Pack
# (packs.py's `grower` entry): a DIY issue/error-sweep Specialist whose
# Knowledge File accumulates what users keep hitting, plus a `grow` Blueprint
# that declares `archetype: grower` so hiring the pack clears the stage-mix
# warning like every other archetype. Metric checks and the `regression`
# replenish kind now exist, so `grow` ships a commented metric-check example
# (uncomment to track a number and fail on regression); automated signal intake
# (issue trackers, APM, crash reports) is the remaining partial piece.
from __future__ import annotations

from pathlib import Path

from alc.intake import (
    load_all_blueprints,
    load_blueprint,
    load_manifest,
    load_specialist,
)
from alc.packs import PACKS, pack_files
from alc.policy import lint
from alc.scaffold import scaffold
from alc.stagepolicy import lint_stage


def _uncomment_metric_example(content: str) -> str:
    """Strip the leading `# ` from the grow Blueprint's commented metric-check
    example, turning the inert block into a live second check.

    Mirrors what an operator does by hand (delete the comment markers). The two
    replaces target exactly the example-body lines: the `- name: bundle-size`
    bullet (re-indented to the check list) and its `#   ` field lines (re-indented
    to four spaces under the bullet). The prose intro lines keep their `# ` and
    stay comments — proof the block's boundaries are unambiguous.
    """
    return content.replace(
        "\n  # - name: bundle-size", "\n  - name: bundle-size"
    ).replace("\n  #   ", "\n    ")


class TestPackRegistration:
    def test_grower_is_registered(self) -> None:
        assert "grower" in PACKS
        assert callable(PACKS["grower"])


class TestPackFilesGrower:
    def test_returns_the_expected_relative_paths(self) -> None:
        files = pack_files("grower", stacks=[])
        assert set(files) == {
            ".alc/specialists/listen.yaml",
            ".alc/blueprints/grow.md",
        }

    def test_listen_specialist_uses_the_default_plan_blueprint(self) -> None:
        content = pack_files("grower", stacks=[])[".alc/specialists/listen.yaml"]
        assert "blueprint: plan" in content

    def test_content_is_the_same_regardless_of_detected_stacks(self) -> None:
        # listen.yaml is stack-agnostic — the sweep is DIY, not stack-specific.
        stacks = [("Python", "python", [("test", ["pytest", "-q"])])]
        assert (
            pack_files("grower", stacks=[])[".alc/specialists/listen.yaml"]
            == pack_files("grower", stacks)[".alc/specialists/listen.yaml"]
        )

    def test_declares_itself_diy_and_partial(self) -> None:
        # T12: "Say plainly, in the pack's own files, that it is partial."
        content = pack_files("grower", stacks=[])[".alc/specialists/listen.yaml"]
        assert "DIY" in content
        assert "Phase" in content  # names the later phase(s) that complete it

    def test_grow_blueprint_carries_the_grower_archetype_label(self) -> None:
        # This is what clears `stage-core-archetype-missing` for grower, exactly
        # like the other packs' Blueprints declare their own archetype.
        content = pack_files("grower", stacks=[])[".alc/blueprints/grow.md"]
        assert "archetype: grower" in content

    def test_grow_blueprint_references_the_primary_stack_check_set(self) -> None:
        stacks = [("Python", "python", [("test", ["pytest", "-q"])])]
        files = pack_files("grower", stacks)
        assert "check_set: python" in files[".alc/blueprints/grow.md"]

    def test_no_check_set_line_when_no_stack_was_detected(self) -> None:
        files = pack_files("grower", stacks=[])
        assert "check_set:" not in files[".alc/blueprints/grow.md"]

    def test_grow_blueprint_keeps_an_inline_check_regardless_of_check_set(self) -> None:
        # An empty check_set (no stack tooling on PATH) must never leave the
        # Blueprint with zero checks — the inline smoke keeps it lint-clean.
        stacks = [("Python", "python", [("test", ["pytest", "-q"])])]
        files = pack_files("grower", stacks)
        assert '["true"]' in files[".alc/blueprints/grow.md"]


# ---------------------------------------------------------------------------
# Loading is strict: Specialists are pydantic-validated YAML — a pack file
# that fails its loader is a defect.
# ---------------------------------------------------------------------------


def _hire(tmp_path: Path) -> Path:
    """Scaffold a default Operator Layer, then hire the grower pack into it."""
    scaffold(tmp_path)
    files = pack_files("grower", stacks=[])
    for rel_path, text in files.items():
        target = tmp_path / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return tmp_path / ".alc"


class TestGrowerPackLoadsThroughTheRealLoaders:
    def test_listen_loads_as_a_specialist(self, tmp_path: Path) -> None:
        operator_layer = _hire(tmp_path)
        specialist = load_specialist(operator_layer / "specialists", "listen")
        assert specialist.name == "listen"
        assert specialist.blueprint == "plan"
        assert specialist.knowledge_path == ".alc/specialists/listen.knowledge.md"

    def test_listen_references_an_existing_blueprint(self, tmp_path: Path) -> None:
        operator_layer = _hire(tmp_path)
        manifest = load_manifest(operator_layer)
        specialist = load_specialist(operator_layer / "specialists", "listen")
        blueprints = {b.name for b in load_all_blueprints(manifest, operator_layer)}
        assert specialist.blueprint in blueprints

    def test_grow_loads_as_a_blueprint_declaring_the_grower_archetype(
        self, tmp_path: Path
    ) -> None:
        operator_layer = _hire(tmp_path)
        bp = load_blueprint(operator_layer / "blueprints", "grow")
        assert bp.name == "grow"
        assert bp.archetype == "grower"
        assert bp.checks  # never empty — the inline smoke keeps the gate satisfied

    def test_hired_grower_layer_lints_clean(self, tmp_path: Path) -> None:
        operator_layer = _hire(tmp_path)
        manifest = load_manifest(operator_layer)
        blueprints = load_all_blueprints(manifest, operator_layer)
        errors = [v for v in lint(manifest, blueprints) if v.severity == "error"]
        assert errors == []


class TestHiringGrowerClearsTheStageMixWarning:
    """The P2 dogfooding gap: `alc team hire grower` used to write only
    listen.yaml (no Blueprint), so `lint_stage` still warned that the growth
    stage was missing a grower — and the hint told you to hire grower, which was
    already hired. The `grow` Blueprint's `archetype: grower` closes the loop."""

    def test_growth_stage_still_warns_when_grower_is_not_hired(
        self, tmp_path: Path
    ) -> None:
        # Baseline: without the grower pack, growth's core `grower` is missing.
        scaffold(tmp_path)
        operator_layer = tmp_path / ".alc"
        manifest = load_manifest(operator_layer).model_copy(update={"stage": "growth"})
        blueprints = load_all_blueprints(manifest, operator_layer)

        missing = [
            v
            for v in lint_stage(manifest, blueprints)
            if v.rule == "stage-core-archetype-missing" and "grower" in v.message
        ]
        assert len(missing) == 1

    def test_hiring_grower_removes_the_missing_grower_warning(
        self, tmp_path: Path
    ) -> None:
        operator_layer = _hire(tmp_path)
        manifest = load_manifest(operator_layer).model_copy(update={"stage": "growth"})
        blueprints = load_all_blueprints(manifest, operator_layer)

        missing = [
            v
            for v in lint_stage(manifest, blueprints)
            if v.rule == "stage-core-archetype-missing" and "grower" in v.message
        ]
        assert missing == []


class TestGrowShipsACommentedMetricCheckExample:
    """The Grower's Boris-distinctive motion is grow WITHOUT regressing via a
    METRIC CHECK. `grow` ships that check as a commented, uncomment-me example:
    inert by default (checks resolve to just the smoke), schema-valid the moment
    an operator strips the `# ` markers."""

    def test_grow_carries_a_commented_metric_check_example(self) -> None:
        content = pack_files("grower", stacks=[])[".alc/blueprints/grow.md"]
        assert "# - name: bundle-size" in content
        assert "metric:" in content
        assert "direction: lower_is_better" in content
        assert "tolerance_pct:" in content
        # The example must stay INERT while shipped: every line that mentions
        # tolerance_pct (the example field AND the prose that names it) is a
        # comment, so YAML never parses a live metric check into the default.
        for line in content.splitlines():
            if "tolerance_pct" in line:
                assert line.lstrip().startswith("#")

    def test_commented_example_is_inert_when_loaded(self, tmp_path: Path) -> None:
        # Default: the block is commented, so `grow` still resolves to exactly
        # the inline smoke check — the pack is lint-clean out of the box.
        operator_layer = _hire(tmp_path)
        bp = load_blueprint(operator_layer / "blueprints", "grow")
        assert [c.name for c in bp.checks] == ["smoke"]

    def test_metric_example_is_schema_valid_when_uncommented(
        self, tmp_path: Path
    ) -> None:
        # Uncommenting the example must yield a real, schema-valid metric check
        # that satisfies Policy Gate rule 14 (metric-requires-direction) — proof
        # the shipped field names and shape are correct, not just illustrative.
        operator_layer = _hire(tmp_path)
        content = pack_files("grower", stacks=[])[".alc/blueprints/grow.md"]
        (operator_layer / "blueprints" / "grow.md").write_text(
            _uncomment_metric_example(content)
        )

        bp = load_blueprint(operator_layer / "blueprints", "grow")
        metric_check = bp.checks[1]
        assert metric_check.metric == ["scripts/bundle_size.py"]
        assert metric_check.direction == "lower_is_better"
        assert metric_check.tolerance_pct == 5.0

        manifest = load_manifest(operator_layer)
        blueprints = load_all_blueprints(manifest, operator_layer)
        errors = [v for v in lint(manifest, blueprints) if v.severity == "error"]
        assert errors == []
