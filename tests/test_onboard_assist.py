# test_onboard_assist.py — Hermetic tests for the OPT-IN engine-assist layer of
# `alc onboard --assist` (onboard.py). Covers the bounded one-shot `engine_assist`
# (valid/garbage/raising engine — never a real engine), the `onboard` prompt
# rendering its `{signals}`/`{tree}` placeholders, and the `build_proposal` merge
# (harvest wins, opt-ins merge, stage stays operator-only) + the `render_preview`
# inferred label. Every engine here is a SCRIPTED fake — no cost, deterministic.
from __future__ import annotations

from pathlib import Path

from alc.engine import Capabilities, EngineResult
from alc.harvest import HarvestedCheck, HarvestReport
from alc.models import Blueprint, Check, Manifest
from alc.onboard import (
    EngineCheckProposal,
    EngineOnboardOutput,
    build_proposal,
    engine_assist,
    render_preview,
)


# ---------------------------------------------------------------------------
# Scripted engine + small builders
# ---------------------------------------------------------------------------


class _ScriptedEngine:
    """Fake engine returning a scripted output_text per call, in order (the last
    entry repeats). `raises=True` makes every run() raise — simulating a
    timeout/crash. Records the call count and the last directive it received."""

    name = "mock"

    def __init__(self, outputs: list[str], raises: bool = False) -> None:
        self._outputs = outputs
        self._raises = raises
        self.calls = 0
        self.last_directive: str | None = None

    def capabilities(self) -> Capabilities:
        return Capabilities()

    def health_check(self) -> bool:
        return True

    def run(self, request) -> EngineResult:
        self.calls += 1
        self.last_directive = request.directive
        if self._raises:
            raise RuntimeError("engine timed out")
        out = self._outputs[min(self.calls - 1, len(self._outputs) - 1)]
        return EngineResult(ok=True, output_text=out)


def _manifest(stage: str | None = None) -> Manifest:
    return Manifest(
        default_engine="mock",
        compute_tiers={"standard": {"mock": "mock-small"}},
        engines={"mock": {"type": "mock"}},
        stage=stage,
    )


def _blueprint(name: str, checks: list[Check]) -> Blueprint:
    return Blueprint(name=name, purpose="x", workflow="w", checks=checks)


_SMOKE = Check(name="smoke", command=["true"])

_MANIFEST_RAW = (
    "version: 1\n"
    "default_engine: mock\n"
    "blueprints_dir: .alc/blueprints\n"
)


def _harvested(name: str, command: list[str]) -> HarvestedCheck:
    return HarvestedCheck(
        name=name,
        command=command,
        shell=None,
        source="package-json",
        source_path="package.json",
        confidence="high",
        available=True,
    )


def _report(checks: list[HarvestedCheck]) -> HarvestReport:
    return HarvestReport(checks=checks, scanned=[], skipped=[])


def _engine_check(name: str, command: list[str]) -> EngineCheckProposal:
    return EngineCheckProposal(
        name=name, command=command, rationale="tree evidence", confidence="high"
    )


_VALID_FENCED = (
    "```json\n"
    '{"checks": [{"name": "build", "command": ["cargo", "build"], '
    '"rationale": "Cargo.toml present", "confidence": "high"}], '
    '"blueprint_opt_ins": {}, "unknowns": ["no CI config found"]}\n'
    "```"
)


# ---------------------------------------------------------------------------
# engine_assist — the bounded one-shot (scripted engine only, never real)
# ---------------------------------------------------------------------------


class TestEngineAssist:
    def test_valid_fenced_json_parses_into_output(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        engine = _ScriptedEngine([_VALID_FENCED])
        monkeypatch.setattr("alc.onboard.resolve_engine", lambda name, engines: engine)

        out = engine_assist(operator_layer.parent, _report([]), operator_layer)

        assert isinstance(out, EngineOnboardOutput)
        assert [c.name for c in out.checks] == ["build"]
        assert out.checks[0].command == ["cargo", "build"]
        assert out.checks[0].confidence == "high"
        assert out.unknowns == ["no CI config found"]
        assert engine.calls == 1  # a single turn was enough

    def test_garbage_twice_returns_none_after_one_retry(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        engine = _ScriptedEngine(["not json at all", "still just prose"])
        monkeypatch.setattr("alc.onboard.resolve_engine", lambda name, engines: engine)

        out = engine_assist(operator_layer.parent, _report([]), operator_layer)

        assert out is None
        assert engine.calls == 2  # ran once, retried exactly once, then gave up

    def test_engine_that_raises_returns_none_never_raises(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        engine = _ScriptedEngine([], raises=True)
        monkeypatch.setattr("alc.onboard.resolve_engine", lambda name, engines: engine)

        # A crash/timeout degrades to harvest-only — it must NOT propagate.
        assert engine_assist(operator_layer.parent, _report([]), operator_layer) is None

    def test_unresolvable_engine_returns_none(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        def _boom(name, engines):
            raise KeyError("no such engine")

        monkeypatch.setattr("alc.onboard.resolve_engine", _boom)

        assert engine_assist(operator_layer.parent, _report([]), operator_layer) is None

    def test_onboard_prompt_renders_signals_and_tree_placeholders(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        engine = _ScriptedEngine(['{"checks": [], "blueprint_opt_ins": {}, "unknowns": []}'])
        monkeypatch.setattr("alc.onboard.resolve_engine", lambda name, engines: engine)

        report = _report([_harvested("test", ["make", "test"])])
        engine_assist(operator_layer.parent, report, operator_layer)

        directive = engine.last_directive
        assert directive is not None
        # No leftover placeholders — both were injected via str.replace.
        assert "{signals}" not in directive
        assert "{tree}" not in directive
        # The harvested signal is present in the {signals} region.
        assert "make test" in directive


# ---------------------------------------------------------------------------
# build_proposal merge — engine ADDS, harvest WINS, stage stays operator-only
# ---------------------------------------------------------------------------


class TestBuildProposalEngineMerge:
    def test_engine_checks_add_to_project_set_with_origin_engine(self) -> None:
        report = _report([_harvested("test", ["make", "test"])])
        engine_out = EngineOnboardOutput(checks=[_engine_check("build", ["cargo", "build"])])

        proposal = build_proposal(
            _manifest(), Path("/x"), [], report, engine_proposal=engine_out
        )

        project = proposal.check_sets["project"]
        assert [c.name for c in project] == ["test", "build"]
        assert project[0].origin == "harvest"
        assert project[1].origin == "engine"
        assert project[1].command == ["cargo", "build"]
        assert project[1].source_path is None

    def test_engine_checks_create_project_set_when_harvest_empty(self) -> None:
        engine_out = EngineOnboardOutput(checks=[_engine_check("build", ["cargo", "build"])])

        proposal = build_proposal(
            _manifest(), Path("/x"), [], _report([]), engine_proposal=engine_out
        )

        assert [c.name for c in proposal.check_sets["project"]] == ["build"]
        # The empty-harvest note is NOT added — the engine filled the gap.
        assert not any("no existing check" in n.lower() for n in proposal.unknowns)

    def test_name_collision_drops_engine_check_harvest_wins(self) -> None:
        report = _report([_harvested("test", ["make", "test"])])
        # The engine proposes a DIFFERENT command under the SAME name — dropped.
        engine_out = EngineOnboardOutput(checks=[_engine_check("test", ["cargo", "test"])])

        proposal = build_proposal(
            _manifest(), Path("/x"), [], report, engine_proposal=engine_out
        )

        project = proposal.check_sets["project"]
        assert len(project) == 1
        assert project[0].origin == "harvest"
        assert project[0].command == ["make", "test"]

    def test_engine_opt_ins_merge_without_overriding_smoke_rule(self) -> None:
        blueprints = [_blueprint("chore", [_SMOKE]), _blueprint("docs", [_SMOKE])]
        report = _report([_harvested("test", ["make", "test"])])
        # "chore" is already opted in by the smoke rule -> NOT overridden.
        # "extra" is new -> added.
        engine_out = EngineOnboardOutput(
            blueprint_opt_ins={"chore": "somethingelse", "extra": "project"}
        )

        proposal = build_proposal(
            _manifest(), Path("/x"), blueprints, report, engine_proposal=engine_out
        )

        assert proposal.blueprint_opt_ins["chore"] == "project"  # smoke rule wins
        assert proposal.blueprint_opt_ins["docs"] == "project"
        assert proposal.blueprint_opt_ins["extra"] == "project"  # engine added it

    def test_engine_never_sets_stage_and_unknowns_are_appended(self) -> None:
        report = _report([_harvested("test", ["make", "test"])])
        engine_out = EngineOnboardOutput(
            checks=[_engine_check("build", ["cargo", "build"])],
            unknowns=["could not determine the deploy step"],
        )

        # Manifest declares a stage; --stage was NOT passed -> stage stays None,
        # and there is no path for the engine to set it.
        proposal = build_proposal(
            _manifest(stage="growth"), Path("/x"), [], report, engine_proposal=engine_out
        )

        assert proposal.stage is None
        assert "could not determine the deploy step" in proposal.unknowns


# ---------------------------------------------------------------------------
# render_preview — engine-origin checks are flagged inferred
# ---------------------------------------------------------------------------


class TestRenderPreviewInferredLabel:
    def test_engine_check_is_labeled_inferred(self) -> None:
        report = _report([_harvested("test", ["make", "test"])])
        engine_out = EngineOnboardOutput(checks=[_engine_check("build", ["cargo", "build"])])
        proposal = build_proposal(
            _manifest(), Path("/x"), [], report, engine_proposal=engine_out
        )

        preview = render_preview(proposal, _MANIFEST_RAW, {})

        assert "inferred — review before trusting" in preview
        # The label attaches to the engine row, not the harvested one: the summary
        # flags exactly one check as inferred.
        assert preview.count("inferred — review before trusting") == 1
