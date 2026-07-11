# test_max_repairs.py — Hermetic tests for the per-Blueprint max_repairs repair budget.
# Exercises: Blueprint model, load_blueprint round-trip, execute_mandate attempt counts,
# and the blueprint-max-repairs-valid policy rule.
from __future__ import annotations

from pathlib import Path


from alc.intake import load_blueprint
from alc.models import Blueprint, Check, Manifest
from alc.policy import has_errors, lint
from alc.runner import execute_mandate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINIMAL_MANIFEST = Manifest(
    version=1,
    default_engine="mock",
    compute_tiers={"standard": {"mock": "mock-small"}},
    engines={"mock": {"type": "mock"}},
)


def _never_passing_check() -> Check:
    """A check whose command always exits non-zero ('false' is a shell built-in)."""
    return Check(name="always-fail", command=["false"])


def _blueprint_with_max_repairs(max_repairs: int | None) -> Blueprint:
    """Return a minimal Blueprint whose single check never passes."""
    return Blueprint(
        name="test-bp",
        purpose="test purpose",
        checks=[_never_passing_check()],
        workflow="# do the thing",
        max_repairs=max_repairs,
    )


def _count_attempts(blueprint: Blueprint, tmp_path: Path) -> int:
    """Run execute_mandate and return the total engine attempt count."""
    report = execute_mandate(
        manifest=_MINIMAL_MANIFEST,
        blueprint=blueprint,
        directive="# Single-Mandate test\nDo nothing.",
        workdir=tmp_path,
    )
    return len(report.attempts)


# ---------------------------------------------------------------------------
# Attempt count assertions
# ---------------------------------------------------------------------------


class TestMaxRepairsAttemptCount:
    """execute_mandate respects the Blueprint's max_repairs budget."""

    def test_max_repairs_zero_yields_one_attempt(self, tmp_path: Path) -> None:
        """max_repairs=0 means no repairs — exactly 1 engine turn."""
        bp = _blueprint_with_max_repairs(max_repairs=0)
        assert _count_attempts(bp, tmp_path) == 1

    def test_max_repairs_one_yields_two_attempts(self, tmp_path: Path) -> None:
        """max_repairs=1 means one repair — exactly 2 engine turns."""
        bp = _blueprint_with_max_repairs(max_repairs=1)
        assert _count_attempts(bp, tmp_path) == 2

    def test_unset_max_repairs_yields_four_attempts(self, tmp_path: Path) -> None:
        """Unset max_repairs falls back to the AssuranceLoop default of 3 repairs -> 4 turns."""
        bp = _blueprint_with_max_repairs(max_repairs=None)
        assert _count_attempts(bp, tmp_path) == 4  # 1 initial + 3 repairs (default)


# ---------------------------------------------------------------------------
# Front-matter round-trip
# ---------------------------------------------------------------------------


class TestLoadBlueprintMaxRepairs:
    """load_blueprint correctly reads max_repairs from the Blueprint's front-matter."""

    def test_max_repairs_round_trip(self, tmp_path: Path) -> None:
        """A blueprint file with max_repairs: 1 is loaded back with max_repairs == 1."""
        blueprints_dir = tmp_path / "blueprints"
        blueprints_dir.mkdir()
        (blueprints_dir / "tight.md").write_text(
            """\
---
name: tight
purpose: Tight repair budget blueprint.
compute_tier: standard
max_repairs: 1
checks:
  - name: smoke
    command: ["true"]
---
# Workflow
Do the task.
"""
        )
        bp = load_blueprint(blueprints_dir, "tight")
        assert bp.max_repairs == 1
        assert bp.name == "tight"

    def test_absent_max_repairs_is_none(self, tmp_path: Path) -> None:
        """A blueprint file without max_repairs is loaded with max_repairs == None."""
        blueprints_dir = tmp_path / "blueprints"
        blueprints_dir.mkdir()
        (blueprints_dir / "default.md").write_text(
            """\
---
name: default
purpose: Default repair budget blueprint.
compute_tier: standard
checks:
  - name: smoke
    command: ["true"]
---
# Workflow
Do the task.
"""
        )
        bp = load_blueprint(blueprints_dir, "default")
        assert bp.max_repairs is None


# ---------------------------------------------------------------------------
# Policy Gate: blueprint-max-repairs-valid
# ---------------------------------------------------------------------------


class TestPolicyMaxRepairs:
    """Policy Gate rule blueprint-max-repairs-valid fires on negative values only."""

    def _make_manifest(self) -> Manifest:
        return _MINIMAL_MANIFEST

    def _make_bp(self, max_repairs: int | None) -> Blueprint:
        """Blueprint with a check so rule 1 doesn't fire, obscuring the target rule."""
        return Blueprint(
            name="test",
            purpose="test purpose",
            checks=[Check(name="smoke", command=["true"])],
            workflow="# do the task",
            max_repairs=max_repairs,
        )

    def test_negative_max_repairs_is_error(self) -> None:
        """max_repairs < 0 produces an error-level Violation for the right rule."""
        bp = self._make_bp(max_repairs=-1)
        violations = lint(_MINIMAL_MANIFEST, [bp])
        matching = [v for v in violations if v.rule == "blueprint-max-repairs-valid"]
        assert len(matching) == 1
        assert matching[0].severity == "error"
        assert "-1" in matching[0].message

    def test_zero_max_repairs_no_violation(self) -> None:
        """max_repairs == 0 is valid — no blueprint-max-repairs-valid violation."""
        bp = self._make_bp(max_repairs=0)
        violations = lint(_MINIMAL_MANIFEST, [bp])
        matching = [v for v in violations if v.rule == "blueprint-max-repairs-valid"]
        assert matching == []

    def test_positive_max_repairs_no_violation(self) -> None:
        """max_repairs > 0 is valid — no blueprint-max-repairs-valid violation."""
        bp = self._make_bp(max_repairs=5)
        violations = lint(_MINIMAL_MANIFEST, [bp])
        matching = [v for v in violations if v.rule == "blueprint-max-repairs-valid"]
        assert matching == []

    def test_absent_max_repairs_no_violation(self) -> None:
        """Absent max_repairs (None) is valid — no blueprint-max-repairs-valid violation."""
        bp = self._make_bp(max_repairs=None)
        violations = lint(_MINIMAL_MANIFEST, [bp])
        matching = [v for v in violations if v.rule == "blueprint-max-repairs-valid"]
        assert matching == []

    def test_negative_max_repairs_blocks_run(self) -> None:
        """has_errors returns True when max_repairs < 0, confirming the run would be blocked."""
        bp = self._make_bp(max_repairs=-1)
        violations = lint(_MINIMAL_MANIFEST, [bp])
        assert has_errors(violations)
