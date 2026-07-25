# manifestedit.py — The ONE shared validate-before-persist gate for manifest.yaml.
#
# Both the UI (`ui.service.write_manifest`) and the CLI (`alc onboard`'s
# `onboard.apply`) must prove a CANDIDATE manifest is conformant before writing
# it. This module extracts that gate so there is a single implementation instead
# of two that could drift: it parses the candidate with the real loader and runs
# the Policy Gate lint, returning the blocking violations (empty == OK).
#
# Leaf module — stdlib plus alc.intake/alc.policy/alc.models only. It imports no
# UI code and nothing imports it that it imports back, so there is no cycle.
from __future__ import annotations

import tempfile
from pathlib import Path

from alc.intake import load_all_blueprints, load_manifest
from alc.policy import Violation
from alc.policy import lint as _lint


def validate_manifest_text(candidate_text: str, operator_layer: Path) -> list[Violation]:
    """Validate a CANDIDATE manifest.yaml text; return the violations that BLOCK it.

    Mirrors `ui.service.write_manifest`'s gate exactly so the CLI and the UI
    enforce one identical contract:

    1. Parse the candidate in ISOLATION — written to a throwaway operator layer
       and loaded with the real `load_manifest`, so the project's own manifest is
       never touched. A candidate that does not parse is reported as a single
       error-severity violation (never a raised exception).
    2. Lint the parsed manifest against the project's REAL blueprints (loaded
       from *operator_layer*, matching what `write_manifest` does today — a
       candidate is judged against the blueprints it will actually govern). A
       blueprint that fails to load never masks the manifest lint; it degrades to
       an empty blueprint list, exactly as the service does.

    Only ERROR-severity violations are returned — a warn is advisory and never
    blocks a write, the same distinction `write_manifest` draws when it filters
    `severity == "error"`. An empty list means the candidate is safe to persist.

    Args:
        candidate_text: The proposed manifest.yaml text (not yet on disk).
        operator_layer: The project's `.alc/` directory — READ for its blueprints
            only; this function never writes to it.

    Returns:
        The error-severity Violations that block persisting the candidate; an
        empty list when it is conformant.
    """
    # 1. Parse the candidate in a throwaway operator layer (never the real one).
    with tempfile.TemporaryDirectory() as td:
        tmp_ol = Path(td) / ".alc"
        tmp_ol.mkdir()
        (tmp_ol / "manifest.yaml").write_text(candidate_text)
        try:
            manifest = load_manifest(tmp_ol)
        except Exception as exc:  # noqa: BLE001 — any parse/validation failure blocks
            return [
                Violation(
                    rule="manifest-parse",
                    severity="error",
                    message=f"invalid manifest: {exc}",
                )
            ]

    # 2. Lint against the project's real blueprints (a broken blueprint must not
    #    mask the manifest lint — degrade to an empty list, as the service does).
    try:
        blueprints = load_all_blueprints(manifest, operator_layer)
    except Exception:  # noqa: BLE001
        blueprints = []
    violations = _lint(manifest, blueprints)
    return [v for v in violations if v.severity == "error"]
