# test_intake.py — Robustness tests for the Operator Layer loaders.
from __future__ import annotations

from pathlib import Path

from alc.intake import load_all_loops, load_blueprint
from alc.models import Manifest

# A blueprint whose checks were all commented out — the `checks:` key is present
# but YAML-null. This must not crash; the Policy Gate then reports "no checks".
_NULL_CHECKS_BLUEPRINT = """\
---
name: feature
purpose: All checks commented out.
compute_tier: standard
checks:
  # - name: build
  #   command: ["go", "build", "./..."]
report:
  format: json
  schema:
    status: string
---
# Workflow
1. Do the thing.
"""

# A blueprint whose `report:` key is present but null.
_NULL_REPORT_BLUEPRINT = """\
---
name: feature
purpose: Report key present but null.
compute_tier: standard
checks:
  - name: build
    command: ["go", "build", "./..."]
report:
---
# Workflow
1. Do the thing.
"""


def test_null_checks_is_treated_as_no_checks(tmp_path: Path) -> None:
    """A present-but-null `checks:` loads as no checks instead of crashing."""
    (tmp_path / "feature.md").write_text(_NULL_CHECKS_BLUEPRINT)
    blueprint = load_blueprint(tmp_path, "feature")
    assert blueprint.checks == []


def test_null_report_is_treated_as_absent(tmp_path: Path) -> None:
    """A present-but-null `report:` loads as no report instead of crashing."""
    (tmp_path / "feature.md").write_text(_NULL_REPORT_BLUEPRINT)
    blueprint = load_blueprint(tmp_path, "feature")
    assert blueprint.report is None
    assert len(blueprint.checks) == 1


_NEEDS_SERVICE_BLUEPRINT = """\
---
name: qa
purpose: Validate the running app.
compute_tier: standard
needs_service: true
checks:
  - name: smoke
    command: ["true"]
---
# Workflow
Hit the running app.
"""


def test_needs_service_round_trip(tmp_path: Path) -> None:
    """`needs_service: true` in front-matter is honored (else the F2 harness is unreachable)."""
    (tmp_path / "qa.md").write_text(_NEEDS_SERVICE_BLUEPRINT)
    assert load_blueprint(tmp_path, "qa").needs_service is True


def test_absent_needs_service_defaults_false(tmp_path: Path) -> None:
    """A blueprint without needs_service loads with needs_service == False (feature OFF)."""
    (tmp_path / "feature.md").write_text(_NULL_REPORT_BLUEPRINT)
    assert load_blueprint(tmp_path, "feature").needs_service is False


# ---------------------------------------------------------------------------
# load_all_loops — mirrors load_all_flows / load_all_specialists
# ---------------------------------------------------------------------------


def _manifest() -> Manifest:
    return Manifest(
        version=1,
        default_engine="mock",
        compute_tiers={"standard": {"mock": "mock-small"}},
        engines={"mock": {"type": "mock"}},
    )


_LOOP_TEMPLATE = "name: {name}\nstop:\n  max_cycles: 5\n"


def test_load_all_loops_missing_dir_is_empty(tmp_path: Path) -> None:
    """No loops directory yields an empty list, never a crash (like load_all_flows)."""
    (tmp_path / ".alc").mkdir()
    assert load_all_loops(_manifest(), tmp_path / ".alc") == []


def test_load_all_loops_loads_sorted_by_stem(tmp_path: Path) -> None:
    loops = tmp_path / ".alc" / "loops"
    loops.mkdir(parents=True)
    (loops / "beta.yaml").write_text(_LOOP_TEMPLATE.format(name="beta"))
    (loops / "alpha.yaml").write_text(_LOOP_TEMPLATE.format(name="alpha"))

    result = load_all_loops(_manifest(), tmp_path / ".alc")
    assert [loop.name for loop in result] == ["alpha", "beta"]


def test_load_all_loops_ignores_state_and_ledger_siblings(tmp_path: Path) -> None:
    """The `*.yaml` glob naturally skips a loop's .state.json / .ledger.jsonl siblings."""
    loops = tmp_path / ".alc" / "loops"
    loops.mkdir(parents=True)
    (loops / "alpha.yaml").write_text(_LOOP_TEMPLATE.format(name="alpha"))
    (loops / "alpha.state.json").write_text('{"name": "alpha", "status": "running"}')
    (loops / "alpha.ledger.jsonl").write_text('{"cycle": 1}\n')

    result = load_all_loops(_manifest(), tmp_path / ".alc")
    assert [loop.name for loop in result] == ["alpha"]
