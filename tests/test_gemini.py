# Hermetic tests for the Gemini engine adapter.
# These do NOT require the `gemini` CLI to be installed: they prove the adapter
# integrates with the control plane (distinct capability matrix, Engine-contract
# conformance, registry wiring) without calling any real model.
from __future__ import annotations

from pathlib import Path

from alc.engine import Engine, EngineRequest
from alc.engines.claude_code import ClaudeCodeEngine
from alc.engines.gemini import GeminiEngine, _approval_mode
from alc.engines.registry import resolve_engine


def test_gemini_satisfies_the_engine_contract() -> None:
    """GeminiEngine is structurally a valid Engine (LSP / Protocol conformance)."""
    assert isinstance(GeminiEngine(), Engine)


def test_gemini_declares_a_distinct_capability_matrix() -> None:
    """The portability point: a second engine with a different native surface.

    Gemini relies on control-plane emulation for system append and structured
    output (False), while supporting MCP natively (True) — unlike Claude Code,
    which declares everything native.
    """
    gemini_caps = GeminiEngine().capabilities()
    claude_caps = ClaudeCodeEngine().capabilities()

    assert gemini_caps.native_mcp is True
    assert gemini_caps.native_system_append is False
    assert gemini_caps.native_structured_output is False
    assert gemini_caps != claude_caps


def test_health_check_returns_a_bool_without_raising() -> None:
    """Works whether or not `gemini` is installed (no exception either way)."""
    assert isinstance(GeminiEngine().health_check(), bool)


def test_registry_resolves_the_gemini_type() -> None:
    """The registry wires the 'gemini' type to a GeminiEngine instance (DIP edge)."""
    engine = resolve_engine("gemini", {"gemini": {"type": "gemini"}})
    assert isinstance(engine, GeminiEngine)
    assert engine.name == "gemini"


def test_approval_mode_maps_permission_intent() -> None:
    """A Blueprint's permission_mode maps onto Gemini's --approval-mode."""
    assert _approval_mode(None) == "auto_edit"            # unset == former default
    assert _approval_mode("acceptEdits") == "auto_edit"
    assert _approval_mode("bypassPermissions") == "yolo"  # auto-approve everything
    assert _approval_mode("plan") == "plan"               # raw Gemini mode passes through
    assert _approval_mode("default") == "default"
    assert _approval_mode("nonsense") == "auto_edit"      # unknown -> safe default


def test_run_threads_permission_mode_into_approval_mode(tmp_path: Path, monkeypatch) -> None:
    """run() builds --approval-mode from request.permission_mode (no real gemini call)."""
    captured: dict = {}

    class _FakeProc:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeProc()

    monkeypatch.setattr("alc.engines.gemini.subprocess.run", fake_run)

    GeminiEngine().run(
        EngineRequest(directive="d", workdir=tmp_path, permission_mode="bypassPermissions")
    )
    cmd = captured["cmd"]
    assert cmd[cmd.index("--approval-mode") + 1] == "yolo"

    GeminiEngine().run(EngineRequest(directive="d", workdir=tmp_path))  # unset
    cmd = captured["cmd"]
    assert cmd[cmd.index("--approval-mode") + 1] == "auto_edit"
