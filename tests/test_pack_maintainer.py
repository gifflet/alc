# test_pack_maintainer.py — Hermetic tests for the Maintainer Archetype Pack
# (packs.py's `maintainer` entry): a security patrol Flow gated by the
# `security` check_set, a bare chore Flow, a dependency Specialist, and the
# Loop that refreshes one package at a time.
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from alc.intake import (
    load_all_blueprints,
    load_blueprint,
    load_flow,
    load_loop,
    load_manifest,
    load_specialist,
    resolve_checks,
)
from alc.loop import check_pre_stop
from alc.models import LoopState
from alc.packs import PACKS, pack_files
from alc.policy import lint_flow, validate_loop
from alc.scaffold import scaffold


class TestPackRegistration:
    def test_maintainer_is_registered(self) -> None:
        assert "maintainer" in PACKS
        assert callable(PACKS["maintainer"])


class TestPackFilesMaintainer:
    def test_returns_the_expected_relative_paths(self) -> None:
        files = pack_files("maintainer", stacks=[])
        assert set(files) == {
            ".alc/blueprints/scan.md",
            ".alc/flows/patrol.yaml",
            ".alc/flows/chore.yaml",
            ".alc/specialists/deps.yaml",
            ".alc/loops/deps-refresh.yaml",
        }

    def test_scan_blueprint_references_the_security_check_set(self) -> None:
        content = pack_files("maintainer", stacks=[])[".alc/blueprints/scan.md"]
        assert "check_set: security" in content

    def test_scan_blueprint_keeps_an_inline_check_regardless_of_check_set(self) -> None:
        content = pack_files("maintainer", stacks=[])[".alc/blueprints/scan.md"]
        assert '["true"]' in content

    def test_scan_blueprint_carries_the_maintainer_archetype_label(self) -> None:
        content = pack_files("maintainer", stacks=[])[".alc/blueprints/scan.md"]
        assert "archetype: maintainer" in content

    def test_scan_content_is_the_same_regardless_of_detected_stacks(self) -> None:
        # `security` is a fixed name, not stack-derived — unlike Builder/Sweeper's
        # check_set_line, the scan Blueprint never varies with the detected stacks.
        stacks = [("Python", "python", [("test", ["pytest", "-q"])])]
        assert (
            pack_files("maintainer", stacks=[])[".alc/blueprints/scan.md"]
            == pack_files("maintainer", stacks)[".alc/blueprints/scan.md"]
        )

    def test_patrol_flow_chains_a_verify_only_scan_then_a_fix_stage(self) -> None:
        content = pack_files("maintainer", stacks=[])[".alc/flows/patrol.yaml"]
        assert "blueprint: scan" in content
        assert "verify_only: true" in content
        assert "blueprint: chore" in content

    def test_chore_flow_wraps_the_default_chore_blueprint(self) -> None:
        content = pack_files("maintainer", stacks=[])[".alc/flows/chore.yaml"]
        assert "blueprint: chore" in content

    def test_deps_specialist_uses_the_chore_blueprint(self) -> None:
        content = pack_files("maintainer", stacks=[])[".alc/specialists/deps.yaml"]
        assert "blueprint: chore" in content

    def test_deps_refresh_loop_replenishes_via_the_deps_specialist(self) -> None:
        content = pack_files("maintainer", stacks=[])[".alc/loops/deps-refresh.yaml"]
        assert "kind: specialist" in content
        assert "ref: deps" in content

    def test_deps_refresh_loop_task_names_the_real_outdated_command_per_stack(self) -> None:
        # A YAML folded scalar (`>`) collapses line-wrap whitespace, so the
        # source's own wrapping would make a raw substring check brittle —
        # parse the YAML and assert on the resulting task string instead.
        content = pack_files("maintainer", stacks=[])[".alc/loops/deps-refresh.yaml"]
        task = yaml.safe_load(content)["replenish"]["task"]
        assert "pip list --outdated" in task
        assert "npm outdated" in task
        assert "go list -m -u all" in task
        assert "cargo outdated" in task

    def test_deps_refresh_loop_task_wires_depends_on_between_related_majors(self) -> None:
        content = pack_files("maintainer", stacks=[])[".alc/loops/deps-refresh.yaml"]
        task = yaml.safe_load(content)["replenish"]["task"]
        assert "--depends-on" in task
        assert "--id" in task

    def test_deps_refresh_loop_declares_the_maintainer_archetype(self) -> None:
        # The loop's scheduled spend IS maintainer work; the tag is what lets a
        # drain through an archetype-less blueprint attribute its runs correctly
        # (instead of falling into the `(none)` bucket).
        content = pack_files("maintainer", stacks=[])[".alc/loops/deps-refresh.yaml"]
        assert yaml.safe_load(content)["archetype"] == "maintainer"

    def test_deps_refresh_loop_declares_a_usd_budget_cost_ceiling(self) -> None:
        # GAP 2: max_cycles alone is not a cost ceiling — a real-engine loop can
        # spend ~$50 before 10 cycles elapse. The out-of-box loop must carry a
        # usd budget cap. Parse the YAML (not a raw substring) so the block's
        # exact layout stays free to change.
        content = pack_files("maintainer", stacks=[])[".alc/loops/deps-refresh.yaml"]
        stop = yaml.safe_load(content)["stop"]
        assert stop["budget"] == {"unit": "usd", "max": 10}

    def test_deps_refresh_task_steers_chores_off_the_package_manager_install(self) -> None:
        # GAP 4a: env-refresh (f394f0b) reinstalls structurally before the checks
        # and updates the lockfile whenever a manifest changes, so a chore told to
        # "run npm install" double-installs. The replenish prompt must steer chores
        # off it — parse the folded scalar (line-wrap whitespace is brittle) and
        # assert the steer is present AND the existing --touches guidance survives.
        content = pack_files("maintainer", stacks=[])[".alc/loops/deps-refresh.yaml"]
        task = yaml.safe_load(content)["replenish"]["task"]
        assert "Do NOT tell a chore to run the package-manager install" in task
        assert "--touches" in task


# ---------------------------------------------------------------------------
# Loading is strict: flows, specialists, and loops are pydantic-validated
# YAML — a pack file that fails its loader is a defect.
# ---------------------------------------------------------------------------


def _hire(tmp_path: Path) -> Path:
    """Scaffold a default Operator Layer, then hire the maintainer pack into it."""
    scaffold(tmp_path)
    files = pack_files("maintainer", stacks=[])
    for rel_path, text in files.items():
        target = tmp_path / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return tmp_path / ".alc"


class TestMaintainerPackLoadsThroughTheRealLoaders:
    def test_deps_loads_as_a_specialist(self, tmp_path: Path) -> None:
        operator_layer = _hire(tmp_path)
        specialist = load_specialist(operator_layer / "specialists", "deps")
        assert specialist.name == "deps"
        assert specialist.blueprint == "chore"
        assert specialist.knowledge_path == ".alc/specialists/deps.knowledge.md"

    def test_deps_refresh_loads_as_a_loop_definition(self, tmp_path: Path) -> None:
        operator_layer = _hire(tmp_path)
        loop_def = load_loop(operator_layer / "loops", "deps-refresh")
        assert loop_def.replenish is not None
        assert loop_def.replenish.kind == "specialist"
        assert loop_def.replenish.ref == "deps"
        assert loop_def.stop.max_cycles > 0
        assert loop_def.archetype == "maintainer"
        # GAP 2: the usd cost ceiling survives the real LoopDefinition loader.
        assert loop_def.stop.budget is not None
        assert loop_def.stop.budget.unit == "usd"
        assert loop_def.stop.budget.max == 10.0

    def test_deps_refresh_pre_stops_on_budget_once_the_usd_cap_is_reached(
        self, tmp_path: Path
    ) -> None:
        # GAP 2: the ceiling is a real backstop — a hired loop whose cumulative usd
        # spend has reached $10 pre-stops with reason "budget" (before max_cycles),
        # so an out-of-box real-engine loop cannot overspend.
        operator_layer = _hire(tmp_path)
        loop_def = load_loop(operator_layer / "loops", "deps-refresh")
        state = LoopState(name="deps-refresh", budget_used={"usd": 10.0})
        assert check_pre_stop(loop_def, state) == "budget"

    def test_patrol_loads_as_a_flow_definition(self, tmp_path: Path) -> None:
        operator_layer = _hire(tmp_path)
        flow = load_flow(operator_layer / "flows", "patrol")
        assert [s.name for s in flow.stages] == ["scan", "fix"]
        assert flow.stages[0].verify_only is True
        assert flow.stages[1].verify_only is False

    def test_chore_loads_as_a_flow_definition(self, tmp_path: Path) -> None:
        operator_layer = _hire(tmp_path)
        flow = load_flow(operator_layer / "flows", "chore")
        assert [s.name for s in flow.stages] == ["apply"]

    def test_deps_refresh_loop_replenish_resolves_to_an_existing_specialist(
        self, tmp_path: Path
    ) -> None:
        operator_layer = _hire(tmp_path)
        manifest = load_manifest(operator_layer)
        loop_def = load_loop(operator_layer / "loops", "deps-refresh")
        assert validate_loop(manifest, operator_layer, loop_def) == []

    def test_patrol_and_chore_flows_resolve_to_existing_blueprints(
        self, tmp_path: Path
    ) -> None:
        operator_layer = _hire(tmp_path)
        manifest = load_manifest(operator_layer)
        blueprints = load_all_blueprints(manifest, operator_layer)
        bp_names = {b.name for b in blueprints}
        for flow_name in ("patrol", "chore"):
            flow = load_flow(operator_layer / "flows", flow_name)
            assert lint_flow(flow, bp_names) == []

    def test_scan_gate_resolves_to_a_non_empty_check_list_even_with_no_scanner(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Constraint: `security` can render EMPTY when no scanner binary
        was on PATH at `alc init` time — the scan gate must still resolve to
        at least one live check (its own inline smoke check)."""
        monkeypatch.setattr("alc.scaffold.shutil.which", lambda cmd: None)
        operator_layer = _hire(tmp_path)
        manifest = load_manifest(operator_layer)
        blueprint = load_blueprint(operator_layer / "blueprints", "scan")

        assert manifest.check_sets.get("security") == []
        assert len(resolve_checks(manifest, blueprint)) >= 1
