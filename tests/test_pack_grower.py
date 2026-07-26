# test_pack_grower.py — Hermetic tests for the Grower Archetype Pack
# (packs.py's `grower` entry): a DIY issue/error-sweep Specialist whose
# Knowledge File accumulates what users keep hitting, plus a `grow` Blueprint
# that declares `archetype: grower` so hiring the pack clears the stage-mix
# warning like every other archetype. Automated signal intake, metric checks,
# and the `regression` replenish kind still land in Phases 4-5 (T12).
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
# that fails its loader is a defect (roadmap-phase-2.md).
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
