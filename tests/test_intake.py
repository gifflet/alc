# test_intake.py — Robustness tests for the Operator Layer loaders.
from __future__ import annotations

from pathlib import Path

from alc.intake import load_blueprint

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
