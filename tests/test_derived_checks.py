# test_derived_checks.py — Hermetic tests for T9: derived checks on a
# verify_only Flow stage (roadmap-phase-4.md). Covers the pure materializer
# (`flow._derive_checks`), the two new Policy Gate rules, the
# FlowStage/DeriveChecksSpec model shape, interpolation safety against a
# hostile value, and end-to-end FlowRunner runs — including the real Sweeper
# pack's `unship` Flow — proving (and disproving) absence at runtime.
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from alc.engine import Capabilities, EngineResult
from alc.flow import FlowRunner, _derive_checks
from alc.intake import load_manifest
from alc.models import (
    DeriveChecksSpec,
    FlowDefinition,
    FlowReport,
    FlowStage,
    RunReport,
    Scorecard,
)
from alc.packs import pack_files
from alc.policy import lint_flow
from alc.scaffold import scaffold
from alc.verifier import Verifier


def _report(output_text: str) -> RunReport:
    """A minimal, otherwise-irrelevant upstream RunReport carrying *output_text*."""
    return RunReport(
        blueprint="map",
        engine="mock",
        success=True,
        attempts=[],
        scorecard=Scorecard(span=0, passes=0, streak=0, touch=0),
        output_text=output_text,
    )


def _spec(shell_template: str = "! grep -rn {value} src/") -> DeriveChecksSpec:
    return DeriveChecksSpec(from_stage="map", field="symbols", shell_template=shell_template)


class TestInconclusiveModelDefaults:
    """`inconclusive` defaults to False on both reports so every existing
    consumer (and every archived report) stays byte-identical."""

    def test_run_report_defaults_inconclusive_false(self) -> None:
        report = RunReport(
            blueprint="x",
            engine="mock",
            success=True,
            attempts=[],
            scorecard=Scorecard(span=0, passes=0, streak=0, touch=0),
            output_text="",
        )
        assert report.inconclusive is False

    def test_flow_report_defaults_inconclusive_false(self) -> None:
        report = FlowReport(
            flow="f",
            engine="mock",
            success=True,
            stages=[],
            scorecard=Scorecard(span=0, passes=0, streak=0, touch=0),
        )
        assert report.inconclusive is False


class TestDeriveChecksSpecShape:
    def test_flow_stage_accepts_derive_checks(self) -> None:
        stage = FlowStage(
            name="gate",
            blueprint="refactor",
            verify_only=True,
            derive_checks=_spec(),
        )
        assert stage.derive_checks is not None
        assert stage.derive_checks.from_stage == "map"
        assert stage.derive_checks.field == "symbols"

    def test_derive_checks_defaults_to_none(self) -> None:
        stage = FlowStage(name="gate", blueprint="refactor", verify_only=True)
        assert stage.derive_checks is None


class TestDeriveChecksMaterialization:
    """Unit tests for the pure `_derive_checks` function — it must never raise,
    whatever shape the upstream report turns out to be."""

    def test_happy_path_one_check_per_item(self) -> None:
        report = _report(json.dumps({"symbols": ["foo_endpoint", "bar_helper"]}))
        checks, warnings, _ = _derive_checks(_spec(), report)
        assert warnings == []
        assert [c.shell for c in checks] == [
            "! grep -rn foo_endpoint src/",
            "! grep -rn bar_helper src/",
        ]
        assert [c.name for c in checks] == ["absence: foo_endpoint", "absence: bar_helper"]

    def test_no_upstream_report_yields_zero_checks_with_a_warning(self) -> None:
        checks, warnings, _ = _derive_checks(_spec(), None)
        assert checks == []
        assert len(warnings) == 1
        assert "produced no report" in warnings[0]

    def test_non_json_output_text_yields_zero_checks_with_a_warning(self) -> None:
        checks, warnings, _ = _derive_checks(_spec(), _report("this is prose, not JSON"))
        assert checks == []
        assert "not valid JSON" in warnings[0]

    def test_empty_output_text_yields_zero_checks_with_a_warning(self) -> None:
        # An empty string is a JSONDecodeError too — must degrade, not raise.
        checks, warnings, _ = _derive_checks(_spec(), _report(""))
        assert checks == []
        assert "not valid JSON" in warnings[0]

    def test_json_that_is_not_an_object_yields_zero_checks_with_a_warning(self) -> None:
        checks, warnings, _ = _derive_checks(_spec(), _report(json.dumps(["a", "b"])))
        assert checks == []
        assert "not a JSON object" in warnings[0]

    def test_missing_field_yields_zero_checks_with_a_warning(self) -> None:
        checks, warnings, _ = _derive_checks(_spec(), _report(json.dumps({"other": []})))
        assert checks == []
        assert "no field 'symbols'" in warnings[0]

    def test_non_list_field_yields_zero_checks_with_a_warning(self) -> None:
        checks, warnings, _ = _derive_checks(
            _spec(), _report(json.dumps({"symbols": "not-a-list"}))
        )
        assert checks == []
        assert "not a list" in warnings[0]

    def test_empty_list_yields_zero_checks_with_a_warning(self) -> None:
        checks, warnings, _ = _derive_checks(_spec(), _report(json.dumps({"symbols": []})))
        assert checks == []
        assert "empty list" in warnings[0]

    def test_non_string_items_are_dropped_but_valid_ones_survive(self) -> None:
        report = _report(json.dumps({"symbols": ["real_symbol", 42, None, {"a": 1}, True]}))
        checks, warnings, _ = _derive_checks(_spec(), report)
        assert len(checks) == 1
        assert checks[0].shell == "! grep -rn real_symbol src/"
        assert len(warnings) == 4
        assert all("dropped non-string item" in w for w in warnings)


class TestDeriveChecksRecoversFencedJson:
    """The `map` Blueprint instructs the model to emit its JSON report inside a
    markdown ```json fence. `_derive_checks` must recover the payload from that
    fence instead of treating the whole (fenced) text as invalid JSON."""

    def test_fenced_empty_list_signals_nothing_to_prove(self) -> None:
        report = _report('```json\n{"symbols": [], "summary": "none"}\n```')
        checks, warnings, nothing_to_prove = _derive_checks(_spec(), report)
        assert checks == []
        assert nothing_to_prove is True
        assert "empty list" in warnings[0]

    def test_fenced_symbols_derive_one_check_each(self) -> None:
        report = _report('```json\n{"symbols": ["foo"]}\n```')
        checks, _, nothing_to_prove = _derive_checks(_spec(), report)
        assert len(checks) == 1
        assert checks[0].shell == "! grep -rn foo src/"
        assert nothing_to_prove is False

    def test_fenced_garbage_is_not_valid_json(self) -> None:
        report = _report("```json\nnot really json\n```")
        checks, warnings, nothing_to_prove = _derive_checks(_spec(), report)
        assert checks == []
        assert nothing_to_prove is False
        assert "not valid JSON" in warnings[0]


class TestDeriveChecksNothingToProve:
    """The third return value distinguishes an upstream stage that legitimately
    reported an EMPTY list ('nothing to prove') from every could-not-derive
    shape. It is True ONLY on the well-formed empty-list branch."""

    def test_empty_list_signals_nothing_to_prove(self) -> None:
        _, _, nothing_to_prove = _derive_checks(
            _spec(), _report(json.dumps({"symbols": []}))
        )
        assert nothing_to_prove is True

    def test_none_report_is_not_nothing_to_prove(self) -> None:
        _, _, nothing_to_prove = _derive_checks(_spec(), None)
        assert nothing_to_prove is False

    def test_non_json_is_not_nothing_to_prove(self) -> None:
        _, _, nothing_to_prove = _derive_checks(_spec(), _report("prose, not JSON"))
        assert nothing_to_prove is False

    def test_non_dict_is_not_nothing_to_prove(self) -> None:
        _, _, nothing_to_prove = _derive_checks(_spec(), _report(json.dumps(["a"])))
        assert nothing_to_prove is False

    def test_missing_field_is_not_nothing_to_prove(self) -> None:
        _, _, nothing_to_prove = _derive_checks(
            _spec(), _report(json.dumps({"other": []}))
        )
        assert nothing_to_prove is False

    def test_non_list_field_is_not_nothing_to_prove(self) -> None:
        _, _, nothing_to_prove = _derive_checks(
            _spec(), _report(json.dumps({"symbols": "x"}))
        )
        assert nothing_to_prove is False

    def test_produced_checks_are_not_nothing_to_prove(self) -> None:
        _, _, nothing_to_prove = _derive_checks(
            _spec(), _report(json.dumps({"symbols": ["foo"]}))
        )
        assert nothing_to_prove is False


class TestDeriveChecksInterpolationIsSafe:
    """Interpolation is a security boundary: the value comes out of a model's
    report and lands in a shell command run via `sh -c`. A hostile value must
    be neutralised by `shlex.quote`, never able to break out of the derived
    command (roadmap-phase-4.md T9)."""

    def test_hostile_value_cannot_execute_extra_commands(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("print('safe')\n")

        marker = tmp_path / "pwned"
        marker_cmdsub = tmp_path / "pwned_cmdsub"
        marker_backtick = tmp_path / "pwned_backtick"
        hostile = (
            f"x; touch {marker}; $(touch {marker_cmdsub}); "
            f"`touch {marker_backtick}`; \"double\"; 'single'"
        )

        report = _report(json.dumps({"symbols": [hostile]}))
        checks, warnings, _ = _derive_checks(_spec(), report)
        assert warnings == []
        assert len(checks) == 1

        results = Verifier().run(checks, tmp_path)
        assert len(results) == 1
        # The whole hostile string was treated as ONE literal grep pattern —
        # it is absent from app.py, so the negated check passes cleanly.
        assert results[0].passed is True
        assert results[0].exit_code == 0
        # None of the injected side-commands ran.
        assert not marker.exists()
        assert not marker_cmdsub.exists()
        assert not marker_backtick.exists()

    def test_a_literal_occurrence_of_the_hostile_string_is_still_found(
        self, tmp_path: Path
    ) -> None:
        # The flip side of safety: quoting must not defeat the grep itself.
        (tmp_path / "src").mkdir()
        hostile = "leftover_symbol; rm -rf /tmp"
        (tmp_path / "src" / "app.py").write_text(f"# {hostile}\n")

        report = _report(json.dumps({"symbols": [hostile]}))
        checks, _, _ = _derive_checks(_spec(), report)

        results = Verifier().run(checks, tmp_path)
        assert results[0].passed is False  # grep found it -> the negated check fails


class TestLintFlowDeriveChecksRules:
    def test_shell_template_without_value_placeholder_is_an_error(self) -> None:
        flow = FlowDefinition(
            name="unship",
            stages=[
                FlowStage(name="map", blueprint="map"),
                FlowStage(
                    name="gate",
                    blueprint="refactor",
                    verify_only=True,
                    derive_checks=_spec(shell_template="echo nothing to interpolate"),
                ),
            ],
        )
        violations = lint_flow(flow, {"map", "refactor"})
        template_violations = [
            v for v in violations if v.rule == "flow-derive-checks-template-has-value"
        ]
        assert len(template_violations) == 1
        assert template_violations[0].severity == "error"

    def test_from_stage_referencing_a_later_stage_is_an_error(self) -> None:
        flow = FlowDefinition(
            name="unship",
            stages=[
                FlowStage(name="gate", blueprint="refactor", verify_only=True, derive_checks=_spec()),
                FlowStage(name="map", blueprint="map"),
            ],
        )
        violations = lint_flow(flow, {"map", "refactor"})
        assert any(v.rule == "flow-derive-checks-from-stage-earlier" for v in violations)
        assert all(
            v.severity == "error"
            for v in violations
            if v.rule == "flow-derive-checks-from-stage-earlier"
        )

    def test_from_stage_referencing_itself_is_an_error(self) -> None:
        flow = FlowDefinition(
            name="unship",
            stages=[
                FlowStage(
                    name="gate",
                    blueprint="refactor",
                    verify_only=True,
                    derive_checks=DeriveChecksSpec(
                        from_stage="gate", field="symbols", shell_template="! grep -rn {value} src/"
                    ),
                ),
            ],
        )
        violations = lint_flow(flow, {"refactor"})
        assert any(v.rule == "flow-derive-checks-from-stage-earlier" for v in violations)

    def test_valid_derive_checks_yields_no_violations(self) -> None:
        flow = FlowDefinition(
            name="unship",
            stages=[
                FlowStage(name="map", blueprint="map"),
                FlowStage(
                    name="gate",
                    blueprint="refactor",
                    verify_only=True,
                    derive_checks=_spec(),
                ),
            ],
        )
        assert lint_flow(flow, {"map", "refactor"}) == []


# ---------------------------------------------------------------------------
# End-to-end: FlowRunner actually wires a verify_only stage's derive_checks
# to an upstream stage's report and runs the materialized checks for real.
# ---------------------------------------------------------------------------


class _ScriptedEngine:
    """Fake engine returning a scripted (side_effect, output_text) per call,
    in order — the last entry repeats once the script runs out."""

    name = "mock"

    def __init__(self, script: list[tuple[Callable[[Path], None] | None, str]]) -> None:
        self._script = script
        self._call_index = 0

    def capabilities(self) -> Capabilities:
        return Capabilities()

    def health_check(self) -> bool:
        return True

    def run(self, request) -> EngineResult:
        side_effect, output_text = self._script[min(self._call_index, len(self._script) - 1)]
        self._call_index += 1
        if side_effect is not None:
            side_effect(request.workdir)
        return EngineResult(ok=True, output_text=output_text)


def _write_map_blueprint(operator_layer: Path) -> None:
    (operator_layer / "blueprints" / "map.md").write_text(
        """\
---
name: map
purpose: Map the symbols a feature exposes.
compute_tier: standard
checks:
  - name: smoke
    command: ["true"]
report:
  format: json
  schema:
    symbols: list
---
# Workflow
Map the feature's symbols.
"""
    )


def _unship_test_flow() -> FlowDefinition:
    """A stand-in for the Sweeper pack's `unship` Flow: map -> remove -> a
    gate that derives its checks from what `map` reported."""
    return FlowDefinition(
        name="unship-test",
        stages=[
            FlowStage(name="map", blueprint="map"),
            FlowStage(name="remove", blueprint="chore"),
            FlowStage(
                name="gate",
                blueprint="chore",
                verify_only=True,
                derive_checks=_spec(),
            ),
        ],
    )


class TestFlowRunnerDerivesChecksAtRuntime:
    def test_gate_passes_once_remove_deletes_every_mapped_symbol(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        _write_map_blueprint(operator_layer)
        project_root = operator_layer.parent
        (project_root / "src").mkdir()
        (project_root / "src" / "app.py").write_text(
            "def old_feature_endpoint(): ...\ndef old_helper(): ...\n"
        )

        def _remove_both(workdir: Path) -> None:
            (workdir / "src" / "app.py").write_text("# nothing left\n")

        engine = _ScriptedEngine(
            [
                (None, json.dumps({"symbols": ["old_feature_endpoint", "old_helper"]})),
                (_remove_both, json.dumps({"status": "ok"})),
            ]
        )
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, engines: engine)

        manifest = load_manifest(operator_layer)
        runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)
        report = runner.run(
            flow=_unship_test_flow(),
            task="unship the old feature",
            engine_override="mock",
            workdir=project_root,
        )

        assert report.success is True
        assert report.stages[-1].success is True
        assert "absence: old_feature_endpoint: pass" in report.stages[-1].output_text
        assert "absence: old_helper: pass" in report.stages[-1].output_text

    def test_gate_fails_when_remove_misses_one_mapped_symbol(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        _write_map_blueprint(operator_layer)
        project_root = operator_layer.parent
        (project_root / "src").mkdir()
        (project_root / "src" / "app.py").write_text(
            "def old_feature_endpoint(): ...\ndef old_helper(): ...\n"
        )

        def _remove_only_one(workdir: Path) -> None:
            (workdir / "src" / "app.py").write_text("def old_helper(): ...\n")

        engine = _ScriptedEngine(
            [
                (None, json.dumps({"symbols": ["old_feature_endpoint", "old_helper"]})),
                (_remove_only_one, json.dumps({"status": "ok"})),
            ]
        )
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, engines: engine)

        manifest = load_manifest(operator_layer)
        runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)
        report = runner.run(
            flow=_unship_test_flow(),
            task="unship the old feature",
            engine_override="mock",
            workdir=project_root,
        )

        assert report.success is False
        assert report.stages[-1].success is False
        # "old_feature_endpoint" was actually removed; "old_helper" survived.
        assert "absence: old_feature_endpoint: pass" in report.stages[-1].output_text
        assert "absence: old_helper: fail" in report.stages[-1].output_text

    def test_malformed_map_report_fails_the_gate_without_raising(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        _write_map_blueprint(operator_layer)
        project_root = operator_layer.parent
        (project_root / "src").mkdir()

        engine = _ScriptedEngine(
            [
                (None, "this is prose, not JSON"),
                (None, json.dumps({"status": "ok"})),
            ]
        )
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, engines: engine)

        manifest = load_manifest(operator_layer)
        runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)
        report = runner.run(
            flow=_unship_test_flow(),
            task="unship the old feature",
            engine_override="mock",
            workdir=project_root,
        )

        assert report.success is False
        assert report.stages[-1].success is False
        assert "not valid JSON" in report.stages[-1].output_text

    def test_map_reporting_zero_symbols_fails_the_gate_rather_than_passing_vacuously(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        _write_map_blueprint(operator_layer)
        project_root = operator_layer.parent
        (project_root / "src").mkdir()

        engine = _ScriptedEngine(
            [
                (None, json.dumps({"symbols": []})),
                (None, json.dumps({"status": "ok"})),
            ]
        )
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, engines: engine)

        manifest = load_manifest(operator_layer)
        runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)
        report = runner.run(
            flow=_unship_test_flow(),
            task="unship the old feature",
            engine_override="mock",
            workdir=project_root,
        )

        assert report.success is False
        assert report.stages[-1].success is False
        assert "empty list" in report.stages[-1].output_text


class TestGateInconclusiveOutcome:
    """A verify_only+derive_checks gate that materializes ZERO checks splits into
    two outcomes: INCONCLUSIVE (the upstream stage succeeded and legitimately
    reported an empty list — nothing to prove) vs a hard FAILURE (the upstream
    report could not be read at all). Both are success=False, but only the first
    is inconclusive=True (which must never be reverted or read as a failure)."""

    def _run(self, operator_layer: Path, monkeypatch, script):
        _write_map_blueprint(operator_layer)
        project_root = operator_layer.parent
        (project_root / "src").mkdir(exist_ok=True)
        (project_root / "src" / "app.py").write_text("def old_helper(): ...\n")
        engine = _ScriptedEngine(script)
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, engines: engine)
        manifest = load_manifest(operator_layer)
        runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)
        return runner.run(
            flow=_unship_test_flow(),
            task="unship the old feature",
            engine_override="mock",
            workdir=project_root,
        )

    def test_empty_legit_upstream_is_inconclusive_not_failed(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        # map succeeds and honestly reports an empty symbol list -> nothing to
        # prove. The flow is inconclusive, not a hard failure.
        report = self._run(
            operator_layer,
            monkeypatch,
            [
                (None, json.dumps({"symbols": []})),
                (None, json.dumps({"status": "ok"})),
            ],
        )
        assert report.success is False
        assert report.inconclusive is True
        assert report.stages[-1].success is False
        assert report.stages[-1].inconclusive is True

    def test_malformed_upstream_is_a_hard_failure_not_inconclusive(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        # map's report is not JSON -> the gate could not derive -> hard failure.
        report = self._run(
            operator_layer,
            monkeypatch,
            [
                (None, "this is prose, not JSON"),
                (None, json.dumps({"status": "ok"})),
            ],
        )
        assert report.success is False
        assert report.inconclusive is False
        assert report.stages[-1].inconclusive is False

    def test_derived_checks_that_fail_are_a_hard_failure(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        # A real symbol is mapped but never removed -> the derived check fails at
        # the shell -> hard failure, never inconclusive.
        report = self._run(
            operator_layer,
            monkeypatch,
            [
                (None, json.dumps({"symbols": ["old_helper"]})),
                (None, json.dumps({"status": "ok"})),
            ],
        )
        assert report.success is False
        assert report.inconclusive is False

    def test_derived_checks_that_pass_are_a_success(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        def _remove(workdir: Path) -> None:
            (workdir / "src" / "app.py").write_text("# gone\n")

        report = self._run(
            operator_layer,
            monkeypatch,
            [
                (None, json.dumps({"symbols": ["old_helper"]})),
                (_remove, json.dumps({"status": "ok"})),
            ],
        )
        assert report.success is True
        assert report.inconclusive is False


class TestGateHandlesFencedMapReportEndToEnd:
    """The real bug: the `map` Blueprint tells the model to wrap its JSON report
    in a ```json fence, so the raw engine text is never bare JSON. Driven through
    the flow, a fenced report must still derive checks / signal nothing-to-prove
    rather than always hard-failing as 'could not derive'."""

    def _run(self, operator_layer: Path, monkeypatch, script):
        _write_map_blueprint(operator_layer)
        project_root = operator_layer.parent
        (project_root / "src").mkdir(exist_ok=True)
        (project_root / "src" / "app.py").write_text("def old_helper(): ...\n")
        engine = _ScriptedEngine(script)
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, engines: engine)
        manifest = load_manifest(operator_layer)
        runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)
        return runner.run(
            flow=_unship_test_flow(),
            task="unship the old feature",
            engine_override="mock",
            workdir=project_root,
        )

    def test_fenced_empty_symbols_is_inconclusive_not_failed(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        # map honestly reports an empty list, but wraps it in a ```json fence.
        report = self._run(
            operator_layer,
            monkeypatch,
            [
                (None, '```json\n{"symbols": [], "summary": "none"}\n```'),
                (None, json.dumps({"status": "ok"})),
            ],
        )
        assert report.success is False
        assert report.inconclusive is True
        assert report.stages[-1].inconclusive is True

    def test_fenced_symbol_derives_a_real_check_that_passes(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        def _remove(workdir: Path) -> None:
            (workdir / "src" / "app.py").write_text("# gone\n")

        report = self._run(
            operator_layer,
            monkeypatch,
            [
                (None, '```json\n{"symbols": ["old_helper"]}\n```'),
                (_remove, json.dumps({"status": "ok"})),
            ],
        )
        assert report.success is True
        assert report.inconclusive is False
        assert "absence: old_helper: pass" in report.stages[-1].output_text

    def test_fenced_garbage_still_hard_fails(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        report = self._run(
            operator_layer,
            monkeypatch,
            [
                (None, "```json\nnot really json\n```"),
                (None, json.dumps({"status": "ok"})),
            ],
        )
        assert report.success is False
        assert report.inconclusive is False
        assert "not valid JSON" in report.stages[-1].output_text


class TestSweeperPackUnshipFlowProvesAbsenceForReal:
    """The Sweeper pack's shipped `unship` Flow (packs.py), run end-to-end,
    must actually prove absence — not ship a placeholder gate."""

    def _hire(self, tmp_path: Path) -> Path:
        scaffold(tmp_path)
        for rel_path, text in pack_files("sweeper", stacks=[]).items():
            target = tmp_path / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        return tmp_path / ".alc"

    def test_unship_flow_gate_passes_when_the_mapped_symbol_is_truly_gone(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from alc.intake import load_flow

        operator_layer = self._hire(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("def dead_export(): ...\n")

        def _delete_dead_export(workdir: Path) -> None:
            (workdir / "src" / "app.py").write_text("# removed\n")

        engine = _ScriptedEngine(
            [
                (None, json.dumps({"symbols": ["dead_export"], "summary": "mapped"})),
                (_delete_dead_export, json.dumps({"status": "ok", "summary": "removed"})),
            ]
        )
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, engines: engine)

        manifest = load_manifest(operator_layer)
        flow = load_flow(operator_layer / "flows", "unship")
        runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)
        report = runner.run(
            flow=flow,
            task="unship dead_export",
            engine_override="mock",
            workdir=tmp_path,
        )

        assert report.success is True
        assert report.stages[-1].success is True

    def test_unship_flow_gate_fails_when_the_mapped_symbol_survives(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from alc.intake import load_flow

        operator_layer = self._hire(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("def dead_export(): ...\n")

        engine = _ScriptedEngine(
            [
                (None, json.dumps({"symbols": ["dead_export"], "summary": "mapped"})),
                (None, json.dumps({"status": "ok", "summary": "left it untouched"})),
            ]
        )
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, engines: engine)

        manifest = load_manifest(operator_layer)
        flow = load_flow(operator_layer / "flows", "unship")
        runner = FlowRunner(manifest=manifest, operator_layer=operator_layer)
        report = runner.run(
            flow=flow,
            task="unship dead_export",
            engine_override="mock",
            workdir=tmp_path,
        )

        assert report.success is False
        assert report.stages[-1].success is False
