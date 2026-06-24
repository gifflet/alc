# Hermetic tests for the Gemini engine adapter.
# These do NOT require the `gemini` CLI to be installed: they prove the adapter
# integrates with the control plane (distinct capability matrix, Engine-contract
# conformance, registry wiring) without calling any real model.
from __future__ import annotations

from alc.engine import Engine
from alc.engines.claude_code import ClaudeCodeEngine
from alc.engines.gemini import GeminiEngine
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
