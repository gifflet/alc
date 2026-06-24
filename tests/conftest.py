# conftest.py — Shared hermetic fixtures.
#
# Tests must not depend on a committed Operator Layer. This fixture writes a
# minimal, self-contained `.alc/` into a tmp dir so the control plane can be
# exercised without any repo-level `.alc/` (the tool repo is not an ALC consumer).
from __future__ import annotations

from pathlib import Path

import pytest

_MANIFEST = """\
version: 1
default_engine: mock
compute_tiers:
  standard:
    mock: mock-small
  deep:
    mock: mock-large
engines:
  mock:
    type: mock
blueprints_dir: .alc/blueprints
flows_dir: .alc/flows
"""

_CHORE = """\
---
name: chore
purpose: Apply a low-risk, well-scoped maintenance change.
compute_tier: standard
checks:
  - name: smoke
    command: ["true"]
report:
  format: json
  schema:
    status: string
---
# Workflow
1. Make the smallest change that satisfies the task; keep it single-purpose.
"""

_PLAN = """\
---
name: plan
purpose: Produce a focused implementation plan, in its own mandate.
compute_tier: deep
checks:
  - name: smoke
    command: ["true"]
report:
  format: json
  schema:
    plan: string
---
# Workflow
1. Produce a concise, step-by-step plan; do not write application code here.
"""

_SHIP = """\
name: ship
description: Plan a change, then implement it — each stage its own mandate.
stages:
  - name: plan
    blueprint: plan
  - name: build
    blueprint: chore
"""


@pytest.fixture
def operator_layer(tmp_path: Path) -> Path:
    """Write a minimal, self-contained Operator Layer into tmp_path/.alc.

    Returns the path to the `.alc/` directory. Fully hermetic: no committed
    Operator Layer is required for the test suite to run.
    """
    alc = tmp_path / ".alc"
    (alc / "blueprints").mkdir(parents=True)
    (alc / "flows").mkdir(parents=True)
    (alc / "manifest.yaml").write_text(_MANIFEST)
    (alc / "blueprints" / "chore.md").write_text(_CHORE)
    (alc / "blueprints" / "plan.md").write_text(_PLAN)
    (alc / "flows" / "ship.yaml").write_text(_SHIP)
    return alc
