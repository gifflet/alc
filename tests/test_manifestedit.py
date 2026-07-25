# test_manifestedit.py — Tests for the shared manifest write-gate (manifestedit.py).
#
# `validate_manifest_text` is the ONE validate-before-persist gate extracted from
# `ui.service.write_manifest`, so the CLI (onboard) and the UI share a single
# gate. Every assertion is against the returned list of blocking Violations —
# the function itself writes nothing to the project's operator layer.
from __future__ import annotations

from pathlib import Path

from alc.manifestedit import validate_manifest_text
from alc.policy import Violation
from alc.scaffold import scaffold


def _scaffolded(tmp_path: Path) -> Path:
    """Scaffold a real `.alc/` and return its operator-layer path."""
    scaffold(tmp_path)
    return tmp_path / ".alc"


class TestValidateManifestText:
    def test_valid_manifest_text_returns_no_violations(self, tmp_path: Path) -> None:
        ol = _scaffolded(tmp_path)
        raw = (ol / "manifest.yaml").read_text()

        violations = validate_manifest_text(raw, ol)

        assert violations == []

    def test_lint_error_returns_violations(self, tmp_path: Path) -> None:
        ol = _scaffolded(tmp_path)
        raw = (ol / "manifest.yaml").read_text()
        # default_engine points at an engine that is not declared -> Policy Gate error.
        bad = raw.replace("default_engine: mock", "default_engine: ghost")

        violations = validate_manifest_text(bad, ol)

        assert violations  # non-empty
        assert all(isinstance(v, Violation) for v in violations)
        assert all(v.severity == "error" for v in violations)

    def test_malformed_yaml_returns_violations(self, tmp_path: Path) -> None:
        ol = _scaffolded(tmp_path)

        violations = validate_manifest_text("default_engine: [oops\n", ol)

        assert violations
        assert all(v.severity == "error" for v in violations)

    def test_never_writes_the_operator_layer(self, tmp_path: Path) -> None:
        # The gate parses the candidate in isolation; the project's own manifest
        # is only READ (for its blueprints), never mutated.
        ol = _scaffolded(tmp_path)
        before = (ol / "manifest.yaml").read_text()
        bad = before.replace("default_engine: mock", "default_engine: ghost")

        validate_manifest_text(bad, ol)

        assert (ol / "manifest.yaml").read_text() == before


class TestServiceParity:
    """`ui.service.write_manifest` now delegates its gate to this module; its own
    behavior is covered by tests/ui/test_api_write.py (which must stay green).
    This asserts the extracted gate agrees with what that endpoint enforces."""

    def test_gate_blocks_exactly_what_write_manifest_blocks(self, tmp_path: Path) -> None:
        ol = _scaffolded(tmp_path)
        raw = (ol / "manifest.yaml").read_text()
        # A clean manifest is accepted; a ghost engine is rejected — the same two
        # outcomes tests/ui/test_api_write.py asserts through the HTTP layer.
        assert validate_manifest_text(raw, ol) == []
        assert validate_manifest_text(
            raw.replace("default_engine: mock", "default_engine: ghost"), ol
        )
