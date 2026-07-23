# test_archetype_field.py — Hermetic tests for the descriptive `archetype:` label.
#
# (a) Front-matter round-trip via load_blueprint.
# (b) Policy Gate: an unrecognised archetype is a warn, never an error.
# (c) Zero runtime effect: execute_mandate copies archetype to RunReport.archetype
#     and nothing about the run (checks, success) changes because of it.
from __future__ import annotations

from pathlib import Path

from alc.intake import load_blueprint
from alc.models import Blueprint, Check, Manifest
from alc.policy import has_errors, lint
from alc.runner import execute_mandate

_MINIMAL_MANIFEST = Manifest(
    version=1,
    default_engine="mock",
    compute_tiers={"standard": {"mock": "mock-small"}},
    engines={"mock": {"type": "mock"}},
)


# ---------------------------------------------------------------------------
# (a) Front-matter round-trip
# ---------------------------------------------------------------------------


class TestLoadBlueprintArchetype:
    def test_archetype_round_trip(self, tmp_path: Path) -> None:
        """A blueprint with archetype: builder is loaded back correctly."""
        blueprints_dir = tmp_path / "blueprints"
        blueprints_dir.mkdir()
        (blueprints_dir / "feature.md").write_text(
            """\
---
name: feature
purpose: Implement a new feature.
compute_tier: standard
archetype: builder
checks:
  - name: smoke
    command: ["true"]
---
# Workflow
Do the task.
"""
        )
        bp = load_blueprint(blueprints_dir, "feature")
        assert bp.archetype == "builder"

    def test_absent_archetype_is_none(self, tmp_path: Path) -> None:
        """A blueprint without archetype is loaded with archetype == None."""
        blueprints_dir = tmp_path / "blueprints"
        blueprints_dir.mkdir()
        (blueprints_dir / "chore.md").write_text(
            """\
---
name: chore
purpose: A standard chore blueprint.
compute_tier: standard
checks:
  - name: smoke
    command: ["true"]
---
# Workflow
Do the task.
"""
        )
        bp = load_blueprint(blueprints_dir, "chore")
        assert bp.archetype is None


# ---------------------------------------------------------------------------
# (b) Policy Gate: blueprint-archetype-known (advisory)
# ---------------------------------------------------------------------------


class TestPolicyArchetype:
    """Policy Gate rule blueprint-archetype-known fires (as a warn) on unknown values only."""

    def _make_bp(self, archetype: str | None) -> Blueprint:
        return Blueprint(
            name="test",
            purpose="test purpose",
            checks=[Check(name="smoke", command=["true"])],
            workflow="# do the task",
            archetype=archetype,
        )

    def test_unknown_archetype_is_warn_not_error(self) -> None:
        bp = self._make_bp(archetype="nonsense")
        violations = lint(_MINIMAL_MANIFEST, [bp])
        matching = [v for v in violations if v.rule == "blueprint-archetype-known"]
        assert len(matching) == 1
        assert matching[0].severity == "warn"
        assert "nonsense" in matching[0].message
        assert not has_errors(violations)

    def test_every_accepted_value_has_no_violation(self) -> None:
        for value in ("prototyper", "builder", "sweeper", "grower", "maintainer"):
            bp = self._make_bp(archetype=value)
            violations = lint(_MINIMAL_MANIFEST, [bp])
            matching = [v for v in violations if v.rule == "blueprint-archetype-known"]
            assert matching == [], f"unexpected violation for archetype={value!r}"

    def test_absent_archetype_no_violation(self) -> None:
        bp = self._make_bp(archetype=None)
        violations = lint(_MINIMAL_MANIFEST, [bp])
        matching = [v for v in violations if v.rule == "blueprint-archetype-known"]
        assert matching == []


# ---------------------------------------------------------------------------
# (c) Zero runtime effect: reporting only
# ---------------------------------------------------------------------------


class TestArchetypeZeroRuntimeEffect:
    def test_archetype_copied_to_run_report(self, tmp_path: Path) -> None:
        bp = Blueprint(
            name="feature",
            purpose="p",
            checks=[Check(name="smoke", command=["true"])],
            workflow="# w",
            archetype="builder",
        )
        report = execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=bp,
            directive="# test\ndo it",
            engine_override="mock",
            workdir=tmp_path,
        )
        assert report.archetype == "builder"

    def test_absent_archetype_run_report_is_none(self, tmp_path: Path) -> None:
        bp = Blueprint(
            name="feature",
            purpose="p",
            checks=[Check(name="smoke", command=["true"])],
            workflow="# w",
        )
        report = execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=bp,
            directive="# test\ndo it",
            engine_override="mock",
            workdir=tmp_path,
        )
        assert report.archetype is None

    def test_archetype_does_not_change_run_outcome(self, tmp_path: Path) -> None:
        """Two otherwise-identical Blueprints differing only by archetype behave alike."""
        checks = [Check(name="smoke", command=["true"])]
        plain = Blueprint(name="feature", purpose="p", checks=checks, workflow="# w")
        labeled = Blueprint(
            name="feature", purpose="p", checks=checks, workflow="# w", archetype="sweeper"
        )

        plain_report = execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=plain,
            directive="# test\ndo it",
            engine_override="mock",
            workdir=tmp_path,
        )
        labeled_report = execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=labeled,
            directive="# test\ndo it",
            engine_override="mock",
            workdir=tmp_path,
        )
        assert plain_report.success == labeled_report.success
        assert plain_report.scorecard == labeled_report.scorecard
