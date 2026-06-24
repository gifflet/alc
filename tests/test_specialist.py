# test_specialist.py — Hermetic tests for the Specialist Recall -> Act -> Learn cycle.
# No real engine is ever called; all tests use MockEngine or its output= param.
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from alc.engines.mock import MockEngine
from alc.intake import load_manifest
from alc.models import Specialist
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
