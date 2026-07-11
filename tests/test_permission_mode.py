# test_permission_mode.py — Hermetic tests for per-Blueprint permission_mode.
#
# (a) Front-matter round-trip via load_blueprint.
# (b) claude-code argv: correct --permission-mode value is emitted (monkeypatched Popen).
# (c) Threading through the Assurance Loop: BOTH initial and repair requests carry the value.
# (d) Policy Gate: invalid permission_mode values trigger an error Violation.
from __future__ import annotations

import io
from pathlib import Path

import pytest

from alc.engine import Capabilities, EngineRequest, EngineResult
from alc.engines.claude_code import ClaudeCodeEngine
from alc.intake import load_blueprint
from alc.models import Blueprint, Check, Manifest
from alc.policy import has_errors, lint
from alc.runner import execute_mandate


# ---------------------------------------------------------------------------
# Shared helpers (mirrors test_clean_config.py pattern)
# ---------------------------------------------------------------------------


class _FakeProc:
    """Minimal stand-in for a Popen object satisfying ClaudeCodeEngine.run()."""

    def __init__(self) -> None:
        self.stdin = io.StringIO()
        self.stdout = io.StringIO('{"type": "result", "result": "done"}\n')
        self.stderr: list[str] = []
        self.returncode = 0

    def wait(self) -> int:
        return 0

    def kill(self) -> None:  # pragma: no cover
        self.returncode = -9


def _capture_argv(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Patch subprocess.Popen in the adapter to record argv without executing."""
    captured: list[list[str]] = []

    def _fake_popen(cmd: list[str], *args: object, **kwargs: object) -> _FakeProc:
        captured.append(list(cmd))
        return _FakeProc()

    monkeypatch.setattr("alc.engines.claude_code.subprocess.Popen", _fake_popen)
    return captured


_MINIMAL_MANIFEST = Manifest(
    version=1,
    default_engine="mock",
    compute_tiers={"standard": {"mock": "mock-small"}},
    engines={"mock": {"type": "mock"}},
)


# ---------------------------------------------------------------------------
# (a) Front-matter round-trip
# ---------------------------------------------------------------------------


class TestLoadBlueprintPermissionMode:
    """load_blueprint correctly reads permission_mode from the Blueprint's front-matter."""

    def test_permission_mode_round_trip(self, tmp_path: Path) -> None:
        """A blueprint with permission_mode: bypassPermissions is loaded back correctly."""
        blueprints_dir = tmp_path / "blueprints"
        blueprints_dir.mkdir()
        (blueprints_dir / "qa.md").write_text(
            """\
---
name: qa
purpose: Run validation suite including runtime commands.
compute_tier: standard
permission_mode: bypassPermissions
checks:
  - name: smoke
    command: ["true"]
---
# Workflow
Run the checks.
"""
        )
        bp = load_blueprint(blueprints_dir, "qa")
        assert bp.permission_mode == "bypassPermissions"

    def test_absent_permission_mode_is_none(self, tmp_path: Path) -> None:
        """A blueprint without permission_mode is loaded with permission_mode == None."""
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
        assert bp.permission_mode is None


# ---------------------------------------------------------------------------
# (b) claude-code argv: --permission-mode value
# ---------------------------------------------------------------------------


class TestClaudeCodeArgvPermissionMode:
    """ClaudeCodeEngine emits the correct --permission-mode flag in the subprocess argv."""

    def test_bypass_permissions_appears_in_argv(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """EngineRequest(permission_mode='bypassPermissions') → argv has the pair."""
        captured = _capture_argv(monkeypatch)
        engine = ClaudeCodeEngine()
        engine.run(
            EngineRequest(
                directive="hi",
                workdir=tmp_path,
                timeout_s=5,
                permission_mode="bypassPermissions",
            )
        )
        argv = captured[0]
        assert "--permission-mode" in argv
        idx = argv.index("--permission-mode")
        assert argv[idx + 1] == "bypassPermissions"
        assert "acceptEdits" not in argv

    def test_none_permission_mode_defaults_to_accept_edits(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """EngineRequest(permission_mode=None) → argv still has --permission-mode acceptEdits."""
        captured = _capture_argv(monkeypatch)
        engine = ClaudeCodeEngine()
        engine.run(
            EngineRequest(
                directive="hi",
                workdir=tmp_path,
                timeout_s=5,
                permission_mode=None,
            )
        )
        argv = captured[0]
        assert "--permission-mode" in argv
        idx = argv.index("--permission-mode")
        assert argv[idx + 1] == "acceptEdits"


# ---------------------------------------------------------------------------
# (c) Threading through the Assurance Loop (initial + repair)
# ---------------------------------------------------------------------------


class _RecordingEngine:
    """A spy engine that records every EngineRequest it receives.

    The single check used in the test always fails, so the Assurance Loop will
    run the initial attempt plus exactly one repair attempt (max_repairs=1),
    giving us two recorded requests to inspect.
    """

    name = "recording"

    def __init__(self) -> None:
        self.received: list[EngineRequest] = []

    def capabilities(self) -> Capabilities:
        return Capabilities()

    def health_check(self) -> bool:
        return True

    def run(self, request: EngineRequest) -> EngineResult:
        self.received.append(request)
        return EngineResult(ok=True, output_text="[recording] ok")


class TestPermissionModeThreading:
    """permission_mode is carried on both the initial and repair EngineRequests."""

    def test_both_attempts_carry_permission_mode(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """execute_mandate with permission_mode set → all attempts have the value."""
        bp = Blueprint(
            name="qa",
            purpose="validation mandate",
            checks=[Check(name="always-fail", command=["false"])],
            workflow="# run",
            max_repairs=1,
            permission_mode="bypassPermissions",
        )
        engine = _RecordingEngine()

        # Patch the name already bound in runner's module namespace (the import is
        # `from alc.engines.registry import resolve_engine`, so we must patch
        # `alc.runner.resolve_engine`, not the registry module attribute).
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine)

        report = execute_mandate(
            manifest=_MINIMAL_MANIFEST,
            blueprint=bp,
            directive="# test\ndo it",
            workdir=tmp_path,
        )

        # The loop ran max_repairs=1, so 2 total attempts (initial + 1 repair).
        assert len(report.attempts) == 2
        assert len(engine.received) == 2
        for req in engine.received:
            assert req.permission_mode == "bypassPermissions"


# ---------------------------------------------------------------------------
# (d) Policy Gate: blueprint-permission-mode-valid
# ---------------------------------------------------------------------------


class TestPolicyPermissionMode:
    """Policy Gate rule blueprint-permission-mode-valid fires on unknown values only."""

    def _make_bp(self, permission_mode: str | None) -> Blueprint:
        """Blueprint with a check so rule 1 doesn't fire, obscuring the target rule."""
        return Blueprint(
            name="test",
            purpose="test purpose",
            checks=[Check(name="smoke", command=["true"])],
            workflow="# do the task",
            permission_mode=permission_mode,
        )

    def test_invalid_permission_mode_is_error(self) -> None:
        """An unrecognised permission_mode yields an error-level Violation."""
        bp = self._make_bp(permission_mode="nonsense")
        violations = lint(_MINIMAL_MANIFEST, [bp])
        matching = [v for v in violations if v.rule == "blueprint-permission-mode-valid"]
        assert len(matching) == 1
        assert matching[0].severity == "error"
        assert "nonsense" in matching[0].message

    def test_bypass_permissions_no_violation(self) -> None:
        """permission_mode='bypassPermissions' is valid — no violation."""
        bp = self._make_bp(permission_mode="bypassPermissions")
        violations = lint(_MINIMAL_MANIFEST, [bp])
        matching = [v for v in violations if v.rule == "blueprint-permission-mode-valid"]
        assert matching == []

    def test_accept_edits_no_violation(self) -> None:
        """permission_mode='acceptEdits' is valid — no violation."""
        bp = self._make_bp(permission_mode="acceptEdits")
        violations = lint(_MINIMAL_MANIFEST, [bp])
        matching = [v for v in violations if v.rule == "blueprint-permission-mode-valid"]
        assert matching == []

    def test_absent_permission_mode_no_violation(self) -> None:
        """Absent permission_mode (None) — no violation from this rule."""
        bp = self._make_bp(permission_mode=None)
        violations = lint(_MINIMAL_MANIFEST, [bp])
        matching = [v for v in violations if v.rule == "blueprint-permission-mode-valid"]
        assert matching == []

    def test_invalid_permission_mode_blocks_run(self) -> None:
        """has_errors returns True when permission_mode is invalid, confirming the run would be blocked."""
        bp = self._make_bp(permission_mode="nonsense")
        violations = lint(_MINIMAL_MANIFEST, [bp])
        assert has_errors(violations)
