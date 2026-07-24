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

    def test_unship_flow_chains_remove_and_a_verify_only_gate(self, tmp_path: Path) -> None:
        # The shipped flow's ACTIVE stages are remove -> a verify_only gate that
        # verifies with the project's REAL checks (require_real_checks); the
        # grep-based prove-absence (map + derive_checks) is a commented opt-in.
        operator_layer = _hire(tmp_path)
        flow = load_flow(operator_layer / "flows", "unship")
        assert [s.name for s in flow.stages] == ["remove", "gate"]
        assert flow.stages[-1].verify_only is True
        assert flow.stages[-1].require_real_checks is True
        assert flow.stages[-1].derive_checks is None

    def test_unship_keeps_the_derive_checks_recipe_as_a_commented_opt_in(self) -> None:
        # The grep-based prove-absence strategy is retained as DOCUMENTATION: every
        # line that names it is a comment, so the loaded flow never activates it.
        # roadmap-phase-4.md T9's recipe (map + derive_checks) stays well-formed.
        content = pack_files("sweeper", stacks=[])[".alc/flows/unship.yaml"]
        for token in ("derive_checks", "from_stage: map", "field: symbols", "{value}"):
            lines = [ln for ln in content.splitlines() if token in ln]
            assert lines, f"expected the opt-in recipe to document {token!r}"
            assert all(ln.lstrip().startswith("#") for ln in lines), (
                f"{token!r} must live in the commented opt-in, not an active stage"
            )
        # The commented grep stays layout-agnostic: it searches the whole repo
        # from its root (no hardcoded `src/` absent in many layouts), skipping
        # ALC's own dir and VCS/deps noise.
        assert "src/" not in content
        assert "--exclude-dir=.alc" in content
        # The recipe still documents the map stage's unique-symbol / empty-list
        # contract (an empty list routes the gate to inconclusive).
        assert "unique" in content.lower()
        assert "empty" in content.lower()

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
        assert [s.name for s in flow.stages] == ["remove", "gate"]
        assert flow.stages[-1].verify_only is True
        assert flow.stages[-1].require_real_checks is True

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
