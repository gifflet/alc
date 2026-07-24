# test_pack_sweeper.py — Hermetic tests for the Sweeper Archetype Pack
# (packs.py's `sweeper` entry): a janitor Specialist carrying the real
# dead-code command per stack, a behavior-preserving refactor Blueprint, the
# sweep Loop that replenishes via the janitor, and the unship Flow it targets.
from __future__ import annotations

from pathlib import Path

from alc.intake import load_all_blueprints, load_flow, load_loop, load_manifest, load_specialist
from alc.packs import PACKS, pack_files
from alc.policy import lint_flow, validate_loop
from alc.scaffold import scaffold


class TestPackRegistration:
    def test_sweeper_is_registered(self) -> None:
        assert "sweeper" in PACKS
        assert callable(PACKS["sweeper"])


class TestPackFilesSweeper:
    def test_returns_the_expected_relative_paths(self) -> None:
        files = pack_files("sweeper", stacks=[])
        assert set(files) == {
            ".alc/blueprints/map.md",
            ".alc/blueprints/refactor.md",
            ".alc/specialists/janitor.yaml",
            ".alc/loops/sweep.yaml",
            ".alc/flows/unship.yaml",
        }

    def test_refactor_blueprint_references_the_primary_stack_check_set(self) -> None:
        stacks = [("Python", "python", [("test", ["pytest", "-q"])])]
        files = pack_files("sweeper", stacks)
        assert "check_set: python" in files[".alc/blueprints/refactor.md"]

    def test_no_check_set_line_when_no_stack_was_detected(self) -> None:
        files = pack_files("sweeper", stacks=[])
        assert "check_set:" not in files[".alc/blueprints/refactor.md"]

    def test_refactor_blueprint_keeps_an_inline_check_regardless_of_check_set(self) -> None:
        stacks = [("Python", "python", [("test", ["pytest", "-q"])])]
        files = pack_files("sweeper", stacks)
        assert '["true"]' in files[".alc/blueprints/refactor.md"]

    def test_refactor_blueprint_carries_the_sweeper_archetype_label(self) -> None:
        files = pack_files("sweeper", stacks=[])
        assert "archetype: sweeper" in files[".alc/blueprints/refactor.md"]

    def test_refactor_blueprint_is_standard_tier(self) -> None:
        files = pack_files("sweeper", stacks=[])
        assert "compute_tier: standard" in files[".alc/blueprints/refactor.md"]

    def test_refactor_blueprint_protects_tests_from_edits(self) -> None:
        # roadmap-phase-3.md T4: the behavior-preserving guarantee stops being
        # prose in the workflow and becomes enforcement.
        content = pack_files("sweeper", stacks=[])[".alc/blueprints/refactor.md"]
        assert 'protect: ["tests/**", "test/**"]' in content

    def test_refactor_blueprint_names_the_real_dead_code_command_per_stack(self) -> None:
        content = pack_files("sweeper", stacks=[])[".alc/blueprints/refactor.md"]
        assert "vulture" in content
        assert "knip" in content or "ts-prune" in content
        assert "staticcheck" in content
        assert "cargo-udeps" in content

    def test_janitor_specialist_uses_the_refactor_blueprint(self) -> None:
        content = pack_files("sweeper", stacks=[])[".alc/specialists/janitor.yaml"]
        assert "blueprint: refactor" in content

    def test_sweep_loop_replenishes_via_a_plan_kind_driven_by_the_janitor(self) -> None:
        content = pack_files("sweeper", stacks=[])[".alc/loops/sweep.yaml"]
        assert "kind: plan" in content
        assert "ref: janitor" in content

    def test_unship_flow_chains_map_remove_and_a_verify_only_gate(self) -> None:
        content = pack_files("sweeper", stacks=[])[".alc/flows/unship.yaml"]
        assert "blueprint: map" in content
        assert content.count("blueprint: refactor") == 2
        assert "verify_only: true" in content

    def test_unship_gate_derives_its_checks_from_the_map_stage(self) -> None:
        # roadmap-phase-4.md T9: the gate proves absence of what `map` found,
        # instead of a fixed check list known only at authoring time.
        content = pack_files("sweeper", stacks=[])[".alc/flows/unship.yaml"]
        assert "derive_checks:" in content
        assert "from_stage: map" in content
        assert "field: symbols" in content
        assert "{value}" in content

    def test_unship_gate_proof_is_layout_agnostic(self) -> None:
        # The absence proof must search the whole tracked codebase, not a
        # hardcoded `src/` dir that does not exist in every project (static
        # sites, non-`src/` layouts) — else the grep vacuously passes and proves
        # nothing. `git grep` searches tracked files regardless of layout.
        content = pack_files("sweeper", stacks=[])[".alc/flows/unship.yaml"]
        # Searches the whole repo from its root (no hardcoded `src/` that would
        # not exist in every layout), skipping ALC's own dir and VCS/deps noise.
        assert "src/" not in content
        assert "--exclude-dir=.alc" in content

    def test_map_blueprint_reports_a_symbols_list(self) -> None:
        content = pack_files("sweeper", stacks=[])[".alc/blueprints/map.md"]
        assert "name: map" in content
        assert "symbols: list" in content

    def test_map_blueprint_maps_only_unique_symbols_or_empty(self) -> None:
        # The gate proves absence by searching for each name literally, so a
        # generic token (e.g. `font-size`) can never be proven absent. The map
        # must list only UNIQUE identifiers, and return an EMPTY list when the
        # removal has none — routing the gate to inconclusive, not a false fail.
        content = pack_files("sweeper", stacks=[])[".alc/blueprints/map.md"]
        assert "unique" in content.lower()
        assert "empty" in content.lower()


# ---------------------------------------------------------------------------
# Loading is strict: flows, specialists, and loops are pydantic-validated
# YAML — a pack file that fails its loader is a defect (roadmap-phase-2.md).
# ---------------------------------------------------------------------------


def _hire(tmp_path: Path) -> Path:
    """Scaffold a default Operator Layer, then hire the sweeper pack into it."""
    scaffold(tmp_path)
    files = pack_files("sweeper", stacks=[])
    for rel_path, text in files.items():
        target = tmp_path / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return tmp_path / ".alc"


class TestSweeperPackLoadsThroughTheRealLoaders:
    def test_janitor_loads_as_a_specialist(self, tmp_path: Path) -> None:
        operator_layer = _hire(tmp_path)
        specialist = load_specialist(operator_layer / "specialists", "janitor")
        assert specialist.name == "janitor"
        assert specialist.blueprint == "refactor"
        assert specialist.knowledge_path == ".alc/specialists/janitor.knowledge.md"

    def test_sweep_loads_as_a_loop_definition(self, tmp_path: Path) -> None:
        operator_layer = _hire(tmp_path)
        loop_def = load_loop(operator_layer / "loops", "sweep")
        assert loop_def.replenish is not None
        assert loop_def.replenish.kind == "plan"
        assert loop_def.replenish.ref == "janitor"
        assert loop_def.stop.max_cycles > 0

    def test_unship_loads_as_a_flow_definition(self, tmp_path: Path) -> None:
        operator_layer = _hire(tmp_path)
        flow = load_flow(operator_layer / "flows", "unship")
        assert [s.name for s in flow.stages] == ["map", "remove", "gate"]
        assert flow.stages[-1].verify_only is True

    def test_sweep_loop_replenish_resolves_to_an_existing_specialist(
        self, tmp_path: Path
    ) -> None:
        operator_layer = _hire(tmp_path)
        manifest = load_manifest(operator_layer)
        loop_def = load_loop(operator_layer / "loops", "sweep")
        assert validate_loop(manifest, operator_layer, loop_def) == []

    def test_unship_flow_stages_resolve_to_existing_blueprints(self, tmp_path: Path) -> None:
        operator_layer = _hire(tmp_path)
        manifest = load_manifest(operator_layer)
        blueprints = load_all_blueprints(manifest, operator_layer)
        flow = load_flow(operator_layer / "flows", "unship")
        assert lint_flow(flow, {b.name for b in blueprints}) == []
