# test_queue.py — Hermetic tests for Unattended Mode: process_queue.
# All tests use the mock engine and isolate: false so no git repository is needed.
from __future__ import annotations

import json
from pathlib import Path

import yaml

from alc.intake import load_manifest
from alc.queue import process_queue
from alc.stagepolicy import mix_health


_TASK_YAML = """\
flow: ship
task: "tidy"
engine: mock
isolate: false
"""

# A task tagged with a provenance archetype (as a loop's run_replenish stamps).
_TAGGED_TASK_YAML = """\
flow: ship
task: "tidy"
engine: mock
isolate: false
archetype: maintainer
"""

# A specialist queue task (kind/name shape), no flow field.
_SPECIALIST_TASK_YAML = """\
kind: specialist
name: db
task: "document the area"
engine: mock
isolate: false
"""


def _write_specialist(operator_layer: Path, name: str = "db") -> None:
    """Write a specialist yaml whose Act blueprint is the fixture's chore blueprint."""
    specialists_dir = operator_layer / "specialists"
    specialists_dir.mkdir(exist_ok=True)
    data = {
        "name": name,
        "area": "the database access layer",
        "blueprint": "chore",
        "knowledge_path": f".alc/specialists/{name}.knowledge.md",
    }
    (specialists_dir / f"{name}.yaml").write_text(yaml.safe_dump(data))


class TestProcessQueueRunsAndArchives:
    def test_process_queue_runs_and_archives(self, operator_layer: Path) -> None:
        """A pending task is executed and moved to done/ with its Gate report."""
        manifest = load_manifest(operator_layer)

        # Create queue dir and drop one task file.
        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "t1.yaml").write_text(_TASK_YAML)

        results = process_queue(manifest, operator_layer)

        # One result, successful, referencing the "ship" flow.
        assert len(results) == 1
        result = results[0]
        assert result.success is True
        assert result.flow == "ship"

        # Task file must have moved out of the top-level queue dir.
        assert not (queue_dir / "t1.yaml").exists()

        # Task file must now be inside done/.
        done_dir = queue_dir / "done"
        assert (done_dir / "t1.yaml").exists()

        # Gate report must exist and be valid JSON with the expected flow name.
        report_path = done_dir / "t1.report.json"
        assert report_path.exists()
        raw = json.loads(report_path.read_text())
        assert raw["flow"] == "ship"
        assert raw["success"] is True


class TestProcessQueueEmptyWhenNoDir:
    def test_process_queue_empty_when_no_dir(self, operator_layer: Path) -> None:
        """process_queue returns [] when the queue directory does not exist."""
        manifest = load_manifest(operator_layer)

        # Ensure the queue dir is absent.
        queue_dir = operator_layer / "queue"
        assert not queue_dir.exists()

        results = process_queue(manifest, operator_layer)
        assert results == []


class TestProcessQueueSkipsAlreadyProcessed:
    def test_process_queue_skips_already_processed(self, operator_layer: Path) -> None:
        """A second tick call returns [] because the task was archived on the first."""
        manifest = load_manifest(operator_layer)

        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "t1.yaml").write_text(_TASK_YAML)

        # First pass: process the task.
        first = process_queue(manifest, operator_layer)
        assert len(first) == 1

        # Second pass: no pending tasks remain.
        second = process_queue(manifest, operator_layer)
        assert second == []


class TestProcessQueueLegacyFlowOnly:
    def test_legacy_flow_only_task_drains(self, operator_layer: Path) -> None:
        """A legacy yaml that only sets `flow:` drains identically (back-compat)."""
        manifest = load_manifest(operator_layer)

        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        # Only flow/task/isolate — no kind, no name (pre-routing format).
        (queue_dir / "legacy.yaml").write_text(
            "flow: ship\ntask: \"tidy\"\nisolate: false\n"
        )

        results = process_queue(manifest, operator_layer)

        assert len(results) == 1
        assert results[0].success is True
        assert results[0].flow == "ship"
        assert (queue_dir / "done" / "legacy.yaml").exists()


class TestArchetypeTagPropagation:
    """A tagged task's provenance archetype fills the archetype-LESS stages of
    its archived report, so Mix Health attributes a drain through an
    archetype-less blueprint (the maintainer's deps-refresh) instead of
    dropping it into the `(none)` bucket. A blueprint-declared stage archetype
    always WINS — the tag only fills None gaps."""

    def _single_stage_chore_flow(self, operator_layer: Path) -> None:
        """A one-stage archetype-less flow, so a drain yields exactly one run."""
        (operator_layer / "flows" / "chore-flow.yaml").write_text(
            "name: chore-flow\ndescription: one chore.\n"
            "stages:\n  - name: apply\n    blueprint: chore\n"
        )

    def test_tag_fills_archetype_less_stages(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "t1.yaml").write_text(_TAGGED_TASK_YAML)

        process_queue(manifest, operator_layer)

        raw = json.loads((queue_dir / "done" / "t1.report.json").read_text())
        # ship's plan + build stages both declare no archetype -> both filled.
        assert [s["archetype"] for s in raw["stages"]] == ["maintainer", "maintainer"]

    def test_untagged_task_keeps_null_stages(self, operator_layer: Path) -> None:
        manifest = load_manifest(operator_layer)
        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "t1.yaml").write_text(_TASK_YAML)

        process_queue(manifest, operator_layer)

        raw = json.loads((queue_dir / "done" / "t1.report.json").read_text())
        assert all(s["archetype"] is None for s in raw["stages"])

    def test_blueprint_declared_archetype_is_not_overridden(
        self, operator_layer: Path
    ) -> None:
        # A stage whose Blueprint declares its OWN archetype keeps it — the tag
        # only fills None gaps, never rewrites deliberate taxonomy.
        (operator_layer / "blueprints" / "tagged.md").write_text(
            "---\nname: tagged\npurpose: A blueprint that declares its archetype.\n"
            "compute_tier: standard\nchecks:\n  - name: smoke\n    command: [\"true\"]\n"
            "archetype: builder\n---\n# Workflow\n1. Nothing.\n"
        )
        (operator_layer / "flows" / "tagged-flow.yaml").write_text(
            "name: tagged-flow\ndescription: one tagged stage.\n"
            "stages:\n  - name: apply\n    blueprint: tagged\n"
        )
        manifest = load_manifest(operator_layer)
        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "t1.yaml").write_text(
            "flow: tagged-flow\ntask: t\nengine: mock\nisolate: false\narchetype: maintainer\n"
        )

        process_queue(manifest, operator_layer)

        raw = json.loads((queue_dir / "done" / "t1.report.json").read_text())
        assert raw["stages"][0]["archetype"] == "builder"

    def test_end_to_end_mix_health_attributes_the_tagged_drain(
        self, operator_layer: Path
    ) -> None:
        self._single_stage_chore_flow(operator_layer)
        manifest = load_manifest(operator_layer)
        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "t1.yaml").write_text(
            "flow: chore-flow\ntask: t\nengine: mock\nisolate: false\narchetype: maintainer\n"
        )

        process_queue(manifest, operator_layer)

        health = mix_health(queue_dir / "done", manifest)
        by_name = {e.archetype: e for e in health.by_archetype}
        assert by_name["maintainer"].runs == 1
        assert None not in by_name  # no `(none)` bucket

    def test_end_to_end_untagged_drain_still_buckets_none(
        self, operator_layer: Path
    ) -> None:
        self._single_stage_chore_flow(operator_layer)
        manifest = load_manifest(operator_layer)
        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "t1.yaml").write_text(
            "flow: chore-flow\ntask: t\nengine: mock\nisolate: false\n"
        )

        process_queue(manifest, operator_layer)

        health = mix_health(queue_dir / "done", manifest)
        assert None in {e.archetype for e in health.by_archetype}


class TestProcessQueueSpecialistTask:
    def test_specialist_task_drains(self, operator_layer: Path) -> None:
        """A specialist queue task runs via run_specialist and archives cleanly."""
        manifest = load_manifest(operator_layer)
        _write_specialist(operator_layer, "db")

        queue_dir = operator_layer / "queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        (queue_dir / "spec.yaml").write_text(_SPECIALIST_TASK_YAML)

        results = process_queue(manifest, operator_layer)

        assert len(results) == 1
        assert results[0].success is True
        assert results[0].flow == "db"

        # The Act -> Learn cycle wrote the Knowledge File.
        knowledge_file = operator_layer.parent / ".alc/specialists/db.knowledge.md"
        assert knowledge_file.exists()

        # Gate report is recorded and the task is archived.
        done_dir = queue_dir / "done"
        assert (done_dir / "spec.yaml").exists()
        raw = json.loads((done_dir / "spec.report.json").read_text())
        assert raw["flow"] == "db"
        assert raw["success"] is True
