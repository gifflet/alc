# test_conduct_stage.py — Hermetic tests for T7: the stage-aware Conductor.
#
# T7 is TWO parts with DIFFERENT guarantees, and the tests are split to match:
#   (a) stage_briefing / plan_flows(stage_briefing=...) — a PROSE nudge folded
#       into the planning directive. Probabilistic by nature: these tests only
#       check the text is (or is not) present, never that a model "obeyed" it.
#   (b) unit_archetype / validate_stage_mix / conduct(strict_stage=...) — plain
#       deterministic code, run AFTER the plan comes back. This is the actual
#       guarantee, and gets the bulk of the coverage.
# No real engine is ever called (MockEngine / small recording stubs only).
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from alc.cli import cmd_conduct
from alc.conduct import conduct, plan_flows
from alc.engine import Capabilities, EngineResult
from alc.engines.mock import MockEngine
from alc.intake import load_manifest
from alc.models import (
    Blueprint,
    ConductorPlan,
    FlowDefinition,
    FlowStage,
    Manifest,
    PlannedUnit,
    Specialist,
)
from alc.runner import PolicyViolationError
from alc.stagepolicy import stage_briefing, unit_archetype, validate_stage_mix

# ---------------------------------------------------------------------------
# Pure-model helpers (no disk I/O) — for stagepolicy-level tests.
# ---------------------------------------------------------------------------


def _manifest(**overrides) -> Manifest:
    defaults = dict(
        version=1,
        default_engine="mock",
        compute_tiers={"standard": {"mock": "mock-small"}, "deep": {"mock": "mock-large"}},
        engines={"mock": {"type": "mock"}},
    )
    defaults.update(overrides)
    return Manifest(**defaults)


def _bp(name: str, archetype: str | None = None) -> Blueprint:
    return Blueprint(name=name, purpose="p", workflow="# w", archetype=archetype)


def _plan(*items: PlannedUnit) -> ConductorPlan:
    return ConductorPlan(items=list(items))


# ---------------------------------------------------------------------------
# (a) stage_briefing — the probabilistic nudge
# ---------------------------------------------------------------------------


class TestStageBriefing:
    def test_none_when_no_stage_declared(self) -> None:
        assert stage_briefing(_manifest()) is None

    def test_names_the_stage_and_its_mix(self) -> None:
        text = stage_briefing(_manifest(stage="growth"))
        assert text is not None
        assert "growth" in text
        # growth core: builder, sweeper, grower; secondary: maintainer.
        for archetype in ("builder", "sweeper", "grower", "maintainer"):
            assert archetype in text

    def test_uses_the_stage_mix_override(self) -> None:
        text = stage_briefing(
            _manifest(stage="growth", stage_mix={"core": ["maintainer"], "secondary": []})
        )
        assert text is not None
        assert "maintainer" in text
        assert "builder" not in text  # the default core it replaced


class _RecordingEngine:
    """Captures the last directive `plan_flows` composed, then returns fixed JSON."""

    name = "mock"

    def __init__(self, output: str) -> None:
        self._output = output
        self.last_directive: str | None = None

    def capabilities(self) -> Capabilities:
        return Capabilities()

    def health_check(self) -> bool:
        return True

    def run(self, request):
        self.last_directive = request.directive
        return EngineResult(ok=True, output_text=self._output)


class TestPlanFlowsStageBriefingAppended:
    def test_briefing_is_appended_after_the_template(self) -> None:
        engine = _RecordingEngine('[{"kind":"flow","name":"ship","task":"x"}]')
        plan_flows(
            engine=engine,
            model=None,
            goal="do stuff",
            catalog_text="- ship: ships it",
            available_flows={"ship"},
            stage_briefing="\n\n## Stage\n\nThis product is at stage 'pre-pmf'.",
        )
        assert engine.last_directive is not None
        assert "## Stage" in engine.last_directive
        assert "pre-pmf" in engine.last_directive
        # The original directive content is still there, untouched.
        assert "do stuff" in engine.last_directive

    def test_no_briefing_leaves_the_directive_untouched(self) -> None:
        engine = _RecordingEngine('[{"kind":"flow","name":"ship","task":"x"}]')
        plan_flows(
            engine=engine,
            model=None,
            goal="do stuff",
            catalog_text="- ship: ships it",
            available_flows={"ship"},
        )
        assert engine.last_directive is not None
        assert "## Stage" not in engine.last_directive


# ---------------------------------------------------------------------------
# (b) unit_archetype — resolving a PlannedUnit's archetype
# ---------------------------------------------------------------------------


class TestUnitArchetype:
    def test_specialist_resolves_via_its_blueprint(self) -> None:
        specialists = {"db": Specialist(name="db", blueprint="build", knowledge_path="k.md")}
        blueprints = {"build": _bp("build", archetype="builder")}
        item = PlannedUnit(kind="specialist", name="db", task="t")
        assert unit_archetype(item, {}, specialists, blueprints) == "builder"

    def test_specialist_with_unarchetyped_blueprint_is_unclassified(self) -> None:
        specialists = {"db": Specialist(name="db", blueprint="build", knowledge_path="k.md")}
        blueprints = {"build": _bp("build", archetype=None)}
        item = PlannedUnit(kind="specialist", name="db", task="t")
        assert unit_archetype(item, {}, specialists, blueprints) is None

    def test_specialist_with_missing_blueprint_is_unclassified(self) -> None:
        specialists = {"db": Specialist(name="db", blueprint="ghost", knowledge_path="k.md")}
        item = PlannedUnit(kind="specialist", name="db", task="t")
        assert unit_archetype(item, {}, specialists, {}) is None

    def test_unknown_specialist_is_unclassified(self) -> None:
        item = PlannedUnit(kind="specialist", name="ghost", task="t")
        assert unit_archetype(item, {}, {}, {}) is None

    def test_flow_single_stage_resolves(self) -> None:
        flow = FlowDefinition(name="ship", stages=[FlowStage(name="s", blueprint="build")])
        blueprints = {"build": _bp("build", archetype="builder")}
        item = PlannedUnit(kind="flow", name="ship", task="t")
        assert unit_archetype(item, {"ship": flow}, {}, blueprints) == "builder"

    def test_flow_stages_that_agree_resolve(self) -> None:
        flow = FlowDefinition(
            name="ship",
            stages=[
                FlowStage(name="a", blueprint="build1"),
                FlowStage(name="b", blueprint="build2"),
            ],
        )
        blueprints = {
            "build1": _bp("build1", archetype="builder"),
            "build2": _bp("build2", archetype="builder"),
        }
        item = PlannedUnit(kind="flow", name="ship", task="t")
        assert unit_archetype(item, {"ship": flow}, {}, blueprints) == "builder"

    def test_flow_stages_that_disagree_are_unclassified(self) -> None:
        flow = FlowDefinition(
            name="mixed",
            stages=[
                FlowStage(name="a", blueprint="build"),
                FlowStage(name="b", blueprint="grow"),
            ],
        )
        blueprints = {
            "build": _bp("build", archetype="builder"),
            "grow": _bp("grow", archetype="grower"),
        }
        item = PlannedUnit(kind="flow", name="mixed", task="t")
        assert unit_archetype(item, {"mixed": flow}, {}, blueprints) is None

    def test_flow_stage_with_unarchetyped_blueprint_is_unclassified(self) -> None:
        flow = FlowDefinition(name="ship", stages=[FlowStage(name="a", blueprint="plain")])
        blueprints = {"plain": _bp("plain", archetype=None)}
        item = PlannedUnit(kind="flow", name="ship", task="t")
        assert unit_archetype(item, {"ship": flow}, {}, blueprints) is None

    def test_flow_stage_via_specialist_resolves(self) -> None:
        flow = FlowDefinition(name="ship", stages=[FlowStage(name="a", specialist="db")])
        specialists = {"db": Specialist(name="db", blueprint="build", knowledge_path="k.md")}
        blueprints = {"build": _bp("build", archetype="builder")}
        item = PlannedUnit(kind="flow", name="ship", task="t")
        assert unit_archetype(item, {"ship": flow}, specialists, blueprints) == "builder"

    def test_unknown_flow_is_unclassified(self) -> None:
        item = PlannedUnit(kind="flow", name="ghost", task="t")
        assert unit_archetype(item, {}, {}, {}) is None


# ---------------------------------------------------------------------------
# (b) validate_stage_mix — the deterministic post-plan guarantee
# ---------------------------------------------------------------------------


class TestValidateStageMix:
    def test_empty_when_no_stage_declared(self) -> None:
        plan = _plan(PlannedUnit(kind="flow", name="ship", task="t"))
        assert validate_stage_mix(_manifest(), plan, {}, {}, {}) == []

    def test_off_mix_unit_warns(self) -> None:
        manifest = _manifest(stage="pre-pmf")  # core: prototyper, builder, sweeper
        flow = FlowDefinition(name="explore", stages=[FlowStage(name="a", blueprint="grow")])
        blueprints = {"grow": _bp("grow", archetype="grower")}
        plan = _plan(PlannedUnit(kind="flow", name="explore", task="t"))

        violations = validate_stage_mix(manifest, plan, {"explore": flow}, {}, blueprints)

        assert len(violations) == 1
        assert violations[0].rule == "stage-plan-off-mix"
        assert violations[0].severity == "warn"
        assert "explore" in violations[0].message
        assert "grower" in violations[0].message
        assert "pre-pmf" in violations[0].message

    def test_in_core_mix_unit_is_silent(self) -> None:
        manifest = _manifest(stage="pre-pmf")
        flow = FlowDefinition(name="ship", stages=[FlowStage(name="a", blueprint="build")])
        blueprints = {"build": _bp("build", archetype="builder")}
        plan = _plan(PlannedUnit(kind="flow", name="ship", task="t"))
        assert validate_stage_mix(manifest, plan, {"ship": flow}, {}, blueprints) == []

    def test_in_secondary_mix_unit_is_silent(self) -> None:
        manifest = _manifest(stage="growth")  # secondary: maintainer
        flow = FlowDefinition(name="fix", stages=[FlowStage(name="a", blueprint="maint")])
        blueprints = {"maint": _bp("maint", archetype="maintainer")}
        plan = _plan(PlannedUnit(kind="flow", name="fix", task="t"))
        assert validate_stage_mix(manifest, plan, {"fix": flow}, {}, blueprints) == []

    def test_unclassified_unit_is_never_penalised(self) -> None:
        manifest = _manifest(stage="pre-pmf")
        plan = _plan(PlannedUnit(kind="flow", name="ghost", task="t"))  # not in the catalog dicts
        assert validate_stage_mix(manifest, plan, {}, {}, {}) == []

    def test_stage_mix_override_changes_the_comparison(self) -> None:
        manifest = _manifest(stage="pre-pmf", stage_mix={"core": ["grower"], "secondary": []})
        flow = FlowDefinition(name="explore", stages=[FlowStage(name="a", blueprint="grow")])
        blueprints = {"grow": _bp("grow", archetype="grower")}
        plan = _plan(PlannedUnit(kind="flow", name="explore", task="t"))
        assert validate_stage_mix(manifest, plan, {"explore": flow}, {}, blueprints) == []


# ---------------------------------------------------------------------------
# conduct() end-to-end — the plan's stage_warnings and --strict-stage refusal
# ---------------------------------------------------------------------------


def _manifest_yaml(stage: str | None) -> str:
    stage_line = f"stage: {stage}\n" if stage else ""
    return (
        "version: 1\n"
        "default_engine: mock\n"
        "compute_tiers:\n  standard:\n    mock: mock-small\n  deep:\n    mock: mock-large\n"
        "engines:\n  mock:\n    type: mock\n"
        "blueprints_dir: .alc/blueprints\n"
        "flows_dir: .alc/flows\n"
        "queue_dir: .alc/queue\n"
        "specialists_dir: .alc/specialists\n"
        f"{stage_line}"
    )


def _bp_md(name: str, archetype: str | None) -> str:
    archetype_line = f"archetype: {archetype}\n" if archetype else ""
    return f"---\nname: {name}\npurpose: p\ncompute_tier: standard\n{archetype_line}---\n# Workflow\n1. do it.\n"


def _flow_yaml(name: str, blueprints: list[str]) -> str:
    stages = "\n".join(f"  - name: s{i}\n    blueprint: {bp}" for i, bp in enumerate(blueprints))
    return f"name: {name}\ndescription: d\nstages:\n{stages}\n"


def _specialist_yaml(name: str, blueprint: str) -> str:
    return (
        f"name: {name}\narea: a\nblueprint: {blueprint}\n"
        f"knowledge_path: .alc/specialists/{name}.knowledge.md\n"
    )


def _stage_repo(tmp_path: Path, stage: str | None) -> Path:
    """A catalog of pre-pmf-relevant units: `ship`/`db` (builder, in-mix for
    pre-pmf) and `explore`/`listen` (grower, off-mix for pre-pmf), plus `mixed`
    (two disagreeing stages -> unclassified)."""
    alc = tmp_path / ".alc"
    (alc / "blueprints").mkdir(parents=True)
    (alc / "flows").mkdir(parents=True)
    (alc / "specialists").mkdir(parents=True)
    (alc / "manifest.yaml").write_text(_manifest_yaml(stage))
    (alc / "blueprints" / "build.md").write_text(_bp_md("build", "builder"))
    (alc / "blueprints" / "grow.md").write_text(_bp_md("grow", "grower"))
    (alc / "flows" / "ship.yaml").write_text(_flow_yaml("ship", ["build"]))
    (alc / "flows" / "explore.yaml").write_text(_flow_yaml("explore", ["grow"]))
    (alc / "flows" / "mixed.yaml").write_text(_flow_yaml("mixed", ["build", "grow"]))
    (alc / "specialists" / "db.yaml").write_text(_specialist_yaml("db", "build"))
    (alc / "specialists" / "listen.yaml").write_text(_specialist_yaml("listen", "grow"))
    return alc


class TestConductStageWarnings:
    def test_no_stage_declared_yields_no_warnings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator_layer = _stage_repo(tmp_path, stage=None)
        manifest = load_manifest(operator_layer)
        plan_json = json.dumps([{"kind": "flow", "name": "explore", "task": "t"}])
        monkeypatch.setattr(
            "alc.engines.registry.resolve_engine",
            lambda name, engines: MockEngine(output=plan_json),
        )

        report = conduct(manifest=manifest, operator_layer=operator_layer, goal="g", enqueue=True)

        assert report.warnings == []

    def test_off_mix_units_warn_but_the_plan_still_dispatches(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator_layer = _stage_repo(tmp_path, stage="pre-pmf")
        manifest = load_manifest(operator_layer)
        plan_json = json.dumps(
            [
                {"kind": "flow", "name": "ship", "task": "t1"},
                {"kind": "flow", "name": "explore", "task": "t2"},
                {"kind": "specialist", "name": "listen", "task": "t3"},
            ]
        )
        monkeypatch.setattr(
            "alc.engines.registry.resolve_engine",
            lambda name, engines: MockEngine(output=plan_json),
        )

        report = conduct(manifest=manifest, operator_layer=operator_layer, goal="g", enqueue=True)

        assert len(report.warnings) == 2
        assert any("explore" in w for w in report.warnings)
        assert any("listen" in w for w in report.warnings)
        assert not any("ship" in w for w in report.warnings)
        # The warning never blocked the plan — all three units were enqueued.
        assert len(report.enqueued_files) == 3

    def test_disagreeing_flow_stages_never_warn(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator_layer = _stage_repo(tmp_path, stage="pre-pmf")
        manifest = load_manifest(operator_layer)
        plan_json = json.dumps([{"kind": "flow", "name": "mixed", "task": "t"}])
        monkeypatch.setattr(
            "alc.engines.registry.resolve_engine",
            lambda name, engines: MockEngine(output=plan_json),
        )

        report = conduct(manifest=manifest, operator_layer=operator_layer, goal="g", enqueue=True)

        assert report.warnings == []

    def test_strict_stage_refuses_before_any_dispatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator_layer = _stage_repo(tmp_path, stage="pre-pmf")
        manifest = load_manifest(operator_layer)
        plan_json = json.dumps([{"kind": "flow", "name": "explore", "task": "t"}])
        monkeypatch.setattr(
            "alc.engines.registry.resolve_engine",
            lambda name, engines: MockEngine(output=plan_json),
        )

        with pytest.raises(PolicyViolationError, match="explore"):
            conduct(
                manifest=manifest,
                operator_layer=operator_layer,
                goal="g",
                enqueue=True,
                strict_stage=True,
            )

        # Refused BEFORE dispatch — nothing was ever written to the queue.
        queue_dir = operator_layer.parent / manifest.queue_dir
        assert not queue_dir.exists() or list(queue_dir.glob("*.yaml")) == []

    def test_strict_stage_with_an_in_mix_plan_dispatches_normally(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        operator_layer = _stage_repo(tmp_path, stage="pre-pmf")
        manifest = load_manifest(operator_layer)
        plan_json = json.dumps([{"kind": "flow", "name": "ship", "task": "t"}])
        monkeypatch.setattr(
            "alc.engines.registry.resolve_engine",
            lambda name, engines: MockEngine(output=plan_json),
        )

        report = conduct(
            manifest=manifest,
            operator_layer=operator_layer,
            goal="g",
            enqueue=True,
            strict_stage=True,
        )

        assert report.warnings == []
        assert len(report.enqueued_files) == 1


# ---------------------------------------------------------------------------
# cmd_conduct — the CLI's --strict-stage wiring
# ---------------------------------------------------------------------------


def _cli_ns(**overrides) -> argparse.Namespace:
    defaults = dict(
        goal="g",
        engine=None,
        enqueue=True,
        parallel=False,
        concurrency=None,
        tier=None,
        strict_stage=False,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestCmdConductStrictStage:
    def test_strict_stage_refusal_prints_error_and_exits_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        operator_layer = _stage_repo(tmp_path, stage="pre-pmf")
        monkeypatch.chdir(operator_layer.parent)
        plan_json = json.dumps([{"kind": "flow", "name": "explore", "task": "t"}])
        monkeypatch.setattr(
            "alc.engines.registry.resolve_engine",
            lambda name, engines: MockEngine(output=plan_json),
        )

        assert cmd_conduct(_cli_ns(strict_stage=True)) == 1
        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert "explore" in err

    def test_default_mode_warns_on_stderr_and_exits_0(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        operator_layer = _stage_repo(tmp_path, stage="pre-pmf")
        monkeypatch.chdir(operator_layer.parent)
        plan_json = json.dumps([{"kind": "flow", "name": "explore", "task": "t"}])
        monkeypatch.setattr(
            "alc.engines.registry.resolve_engine",
            lambda name, engines: MockEngine(output=plan_json),
        )

        assert cmd_conduct(_cli_ns()) == 0
        err = capsys.readouterr().err
        assert "[WARN]" in err
        assert "explore" in err

    def test_no_stage_declared_prints_no_warnings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        operator_layer = _stage_repo(tmp_path, stage=None)
        monkeypatch.chdir(operator_layer.parent)
        plan_json = json.dumps([{"kind": "flow", "name": "explore", "task": "t"}])
        monkeypatch.setattr(
            "alc.engines.registry.resolve_engine",
            lambda name, engines: MockEngine(output=plan_json),
        )

        assert cmd_conduct(_cli_ns()) == 0
        err = capsys.readouterr().err
        assert "[WARN]" not in err
