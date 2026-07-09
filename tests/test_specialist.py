# test_specialist.py — Hermetic tests for the Specialist Recall -> Act -> Learn cycle.
# No real engine is ever called; all tests use MockEngine or its output= param.
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from alc.engines.mock import MockEngine
from alc.intake import load_manifest
from alc.models import Specialist
from alc.runner import PolicyViolationError
from alc.specialist import compose_act_directive, learn, recall, run_specialist


# ---------------------------------------------------------------------------
# recall — pure unit tests (no fixtures needed)
# ---------------------------------------------------------------------------


class TestRecall:
    def test_recall_missing_returns_empty(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist.md"
        assert recall(missing) == ""

    def test_recall_existing_returns_content(self, tmp_path: Path) -> None:
        knowledge_file = tmp_path / "knowledge.md"
        knowledge_file.write_text("# My knowledge\nSome content here.\n")
        result = recall(knowledge_file)
        assert result == "# My knowledge\nSome content here.\n"


# ---------------------------------------------------------------------------
# compose_act_directive — pure unit tests
# ---------------------------------------------------------------------------


class TestComposeActDirective:
    def _make_blueprint(self, operator_layer: Path):
        from alc.intake import load_blueprint, load_manifest
        manifest = load_manifest(operator_layer)
        blueprints_dir = operator_layer.parent / manifest.blueprints_dir
        return load_blueprint(blueprints_dir, "chore")

    def test_includes_knowledge_when_non_empty(self, operator_layer: Path) -> None:
        blueprint = self._make_blueprint(operator_layer)
        knowledge = "## Tables\n- users\n- orders\n"

        directive = compose_act_directive(blueprint, "document the schema", knowledge)

        assert knowledge in directive
        assert "Specialist knowledge" in directive
        assert blueprint.workflow in directive

    def test_no_knowledge_section_header_when_empty(self, operator_layer: Path) -> None:
        blueprint = self._make_blueprint(operator_layer)

        directive = compose_act_directive(blueprint, "document the schema", "")

        assert "Specialist knowledge" not in directive
        assert blueprint.workflow in directive

    def test_workflow_always_present(self, operator_layer: Path) -> None:
        blueprint = self._make_blueprint(operator_layer)

        directive_with = compose_act_directive(blueprint, "task", "some knowledge")
        directive_without = compose_act_directive(blueprint, "task", "")

        assert blueprint.workflow in directive_with
        assert blueprint.workflow in directive_without

    def test_output_contract_appended_last(self, operator_layer: Path) -> None:
        blueprint = self._make_blueprint(operator_layer)

        directive = compose_act_directive(
            blueprint, "task", "some knowledge", output_contract="MY CONTRACT"
        )

        # The contract lands after the workflow and under the required header.
        assert "## Output contract (required by ALC" in directive
        assert directive.endswith("MY CONTRACT")
        assert directive.index(blueprint.workflow) < directive.index("MY CONTRACT")

    def test_none_output_contract_is_byte_identical(self, operator_layer: Path) -> None:
        blueprint = self._make_blueprint(operator_layer)

        with_none = compose_act_directive(blueprint, "task", "kn", output_contract=None)
        without_arg = compose_act_directive(blueprint, "task", "kn")

        assert with_none == without_arg


# ---------------------------------------------------------------------------
# learn — uses MockEngine with canned output
# ---------------------------------------------------------------------------


class TestLearn:
    def test_keeps_old_when_engine_returns_blank(self) -> None:
        engine = MockEngine(output="   ")
        result = learn(engine, None, "OLD", "area", "task", "act out")
        assert result == "OLD"

    def test_keeps_old_when_engine_returns_empty_string(self) -> None:
        engine = MockEngine(output="")
        result = learn(engine, None, "ORIGINAL", "area", "task", "act out")
        assert result == "ORIGINAL"

    def test_updates_when_engine_returns_text(self) -> None:
        engine = MockEngine(output="NEW KNOWLEDGE")
        result = learn(engine, None, "OLD", "area", "task", "act out")
        assert result == "NEW KNOWLEDGE"

    def test_passes_model_to_engine_request(self) -> None:
        """Verify the model param is forwarded (MockEngine ignores it, but no error)."""
        engine = MockEngine(output="UPDATED")
        result = learn(engine, "mock-small", "base", "area", "task", "output")
        assert result == "UPDATED"

    def test_forwards_workdir_to_engine_request(self, tmp_path: Path) -> None:
        """The Learn engine turn must run in the given workdir, not always cwd."""

        class _RecordingEngine:
            name = "mock"

            def __init__(self) -> None:
                self.seen_workdir: Path | None = None

            def capabilities(self):
                from alc.engine import Capabilities

                return Capabilities()

            def health_check(self) -> bool:
                return True

            def run(self, request):
                from alc.engine import EngineResult

                self.seen_workdir = request.workdir
                return EngineResult(ok=True, output_text="UPDATED")

        engine = _RecordingEngine()
        learn(engine, None, "base", "area", "task", "output", workdir=tmp_path)
        assert engine.seen_workdir == tmp_path


# ---------------------------------------------------------------------------
# run_specialist — integration test using operator_layer fixture
# ---------------------------------------------------------------------------


class TestRunSpecialist:
    def _write_specialist(self, operator_layer: Path, blueprint: str = "chore") -> Specialist:
        """Write a db.yaml specialist file and return the loaded Specialist."""
        specialists_dir = operator_layer / "specialists"
        specialists_dir.mkdir(exist_ok=True)
        data = {
            "name": "db",
            "area": "the database access layer",
            "blueprint": blueprint,
            "knowledge_path": ".alc/specialists/db.knowledge.md",
        }
        (specialists_dir / "db.yaml").write_text(yaml.safe_dump(data))
        return Specialist.model_validate(data)

    def test_run_specialist_acts_and_writes_knowledge(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        specialist = self._write_specialist(operator_layer, blueprint="chore")

        report = run_specialist(
            manifest=manifest,
            operator_layer=operator_layer,
            specialist=specialist,
            task="document the area",
            engine_override="mock",
        )

        assert report.act.success is True

        knowledge_file = operator_layer.parent / specialist.knowledge_path
        assert knowledge_file.exists(), "Knowledge File must be created after a successful Act"

        assert report.knowledge_updated is True

    def test_run_specialist_report_fields(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        specialist = self._write_specialist(operator_layer)

        report = run_specialist(
            manifest=manifest,
            operator_layer=operator_layer,
            specialist=specialist,
            task="analyse the ORM",
            engine_override="mock",
        )

        assert report.specialist == "db"
        assert report.act.blueprint == "chore"

    def test_learn_uses_specialist_blueprint_tier(
        self, operator_layer: Path, monkeypatch
    ) -> None:
        # Knob E: Learn runs at the Specialist's own Blueprint tier, not a hardcoded
        # "standard". The fixture's `plan` blueprint is deep-tier (checks pass), so
        # its Learn turn must resolve the deep model.
        manifest = load_manifest(operator_layer)
        specialist = self._write_specialist(operator_layer, blueprint="plan")
        captured: dict = {}

        def fake_learn(engine, model, *args, **kwargs):
            captured["model"] = model
            return "KNOWLEDGE"

        monkeypatch.setattr("alc.specialist.learn", fake_learn)
        run_specialist(
            manifest=manifest,
            operator_layer=operator_layer,
            specialist=specialist,
            task="tune the area",
            engine_override="mock",
        )
        assert captured["model"] == manifest.compute_tiers["deep"]["mock"]

    def test_knowledge_not_updated_on_failed_act(self, tmp_path: Path) -> None:
        """When Act fails, Learn must not run and Knowledge File must not be created."""
        # Build an operator layer where the chore blueprint's check always fails.
        alc = tmp_path / ".alc"
        (alc / "blueprints").mkdir(parents=True)
        (alc / "specialists").mkdir(parents=True)

        _MANIFEST = """\
version: 1
default_engine: mock
compute_tiers:
  standard:
    mock: mock-small
engines:
  mock:
    type: mock
blueprints_dir: .alc/blueprints
flows_dir: .alc/flows
queue_dir: .alc/queue
"""
        # Blueprint with a check that always fails (exit 1).
        _FAILING_BLUEPRINT = """\
---
name: chore
purpose: Apply a maintenance change.
compute_tier: standard
checks:
  - name: always-fail
    command: ["false"]
report:
  format: json
  schema:
    status: string
---
# Workflow
1. Make the smallest change.
"""
        (alc / "manifest.yaml").write_text(_MANIFEST)
        (alc / "blueprints" / "chore.md").write_text(_FAILING_BLUEPRINT)

        data = {
            "name": "db",
            "area": "db layer",
            "blueprint": "chore",
            "knowledge_path": ".alc/specialists/db.knowledge.md",
        }
        (alc / "specialists" / "db.yaml").write_text(yaml.safe_dump(data))

        manifest = load_manifest(alc)
        specialist = Specialist.model_validate(data)

        report = run_specialist(
            manifest=manifest,
            operator_layer=alc,
            specialist=specialist,
            task="do something",
            engine_override="mock",
        )

        assert report.act.success is False
        assert report.knowledge_updated is False
        knowledge_file = alc.parent / specialist.knowledge_path
        assert not knowledge_file.exists()


# ---------------------------------------------------------------------------
# run_specialist — Policy Gate enforcement
# ---------------------------------------------------------------------------


class TestRunSpecialistPolicyGate:
    """run_specialist must enforce the Policy Gate just like MandateRunner.run."""

    def test_unknown_check_set_raises_policy_violation(self, tmp_path: Path) -> None:
        """A blueprint that references a check_set absent from the Manifest raises
        PolicyViolationError before any engine turn starts."""
        alc = tmp_path / ".alc"
        (alc / "blueprints").mkdir(parents=True)
        (alc / "specialists").mkdir(parents=True)

        _MANIFEST_NO_SETS = """\
version: 1
default_engine: mock
compute_tiers:
  standard:
    mock: mock-small
engines:
  mock:
    type: mock
blueprints_dir: .alc/blueprints
flows_dir: .alc/flows
queue_dir: .alc/queue
"""
        # Blueprint references a check_set that does not exist in the manifest.
        _BP_UNKNOWN_SET = """\
---
name: chore
purpose: Apply a maintenance change.
compute_tier: standard
check_set: nonexistent-set
report:
  format: json
  schema:
    status: string
---
# Workflow
1. Make the smallest change.
"""
        (alc / "manifest.yaml").write_text(_MANIFEST_NO_SETS)
        (alc / "blueprints" / "chore.md").write_text(_BP_UNKNOWN_SET)

        data = {
            "name": "db",
            "area": "db layer",
            "blueprint": "chore",
            "knowledge_path": ".alc/specialists/db.knowledge.md",
        }
        (alc / "specialists" / "db.yaml").write_text(yaml.safe_dump(data))

        manifest = load_manifest(alc)
        specialist = Specialist.model_validate(data)

        with pytest.raises(PolicyViolationError):
            run_specialist(
                manifest=manifest,
                operator_layer=alc,
                specialist=specialist,
                task="do something",
                engine_override="mock",
            )
