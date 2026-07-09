# Hermetic tests for the Gemini engine adapter.
# These do NOT require the `gemini` CLI to be installed: they prove the adapter
# integrates with the control plane (distinct capability matrix, Engine-contract
# conformance, registry wiring) without calling any real model.
from __future__ import annotations

import subprocess
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


class _FakeStdout:
    """A stdout pipe whose readline() yields the scripted JSONL lines then EOF."""

    def __init__(self, lines: list[str]) -> None:
        self._it = iter([*lines, ""])

    def readline(self) -> str:
        return next(self._it, "")


def _patch_popen(monkeypatch, captured: dict, stdout_lines: list[str],
                 stderr_lines: tuple[str, ...] = (), returncode: int = 0):
    """Patch subprocess.Popen in the gemini module with a scripted fake."""

    class _FakePopen:
        def __init__(self, cmd, **kwargs) -> None:
            captured["cmd"] = cmd
            captured["stdin"] = kwargs.get("stdin")
            self.returncode = returncode
            self.stdout = _FakeStdout(stdout_lines)
            self.stderr = list(stderr_lines)

        def wait(self) -> int:
            return returncode

        def kill(self) -> None:  # pragma: no cover - timeout path only
            pass

    monkeypatch.setattr("alc.engines.gemini.subprocess.Popen", _FakePopen)


# Real event shapes captured from `gemini … --output-format stream-json`.
_INIT = '{"type":"init","timestamp":"t","session_id":"s","model":"auto"}'
_USER = '{"type":"message","role":"user","content":"do the thing"}'
_ASSISTANT_OK = '{"type":"message","role":"assistant","content":"OK"}'
_RESULT_SUCCESS = (
    '{"type":"result","status":"success","response":"FINAL",'
    '"stats":{"input_tokens":10,"output_tokens":5,"tool_calls":0}}'
)
_RESULT_ERROR = (
    '{"type":"result","status":"error",'
    '"error":{"type":"FatalCancellationError","message":"Operation cancelled."},'
    '"stats":{"input_tokens":2233,"output_tokens":38}}'
)


def test_run_uses_stream_json_and_devnull_stdin(tmp_path: Path, monkeypatch) -> None:
    captured: dict = {}
    _patch_popen(monkeypatch, captured, [_INIT, _ASSISTANT_OK, _RESULT_SUCCESS])

    GeminiEngine().run(
        EngineRequest(directive="d", workdir=tmp_path, permission_mode="bypassPermissions")
    )
    cmd = captured["cmd"]
    assert cmd[cmd.index("--approval-mode") + 1] == "yolo"
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert captured["stdin"] is subprocess.DEVNULL  # never blocks on interactive input


def test_run_returns_response_on_success(tmp_path: Path, monkeypatch) -> None:
    captured: dict = {}
    _patch_popen(monkeypatch, captured, [_INIT, _USER, _ASSISTANT_OK, _RESULT_SUCCESS])

    result = GeminiEngine().run(EngineRequest(directive="d", workdir=tmp_path))
    assert result.ok is True
    assert result.output_text == "FINAL"  # result.response preferred
    assert result.usage.input_tokens == 10


def test_run_falls_back_to_assistant_text(tmp_path: Path, monkeypatch) -> None:
    # A result with no `response` field -> accumulated assistant message content.
    captured: dict = {}
    result_no_response = '{"type":"result","status":"success","stats":{}}'
    _patch_popen(monkeypatch, captured, [_ASSISTANT_OK, result_no_response])

    result = GeminiEngine().run(EngineRequest(directive="d", workdir=tmp_path))
    assert result.ok is True
    assert result.output_text == "OK"


def test_run_surfaces_error_result_as_failure(tmp_path: Path, monkeypatch) -> None:
    # A 503/cancellation ends in a result:error event -> ok=False with the message,
    # NOT a silent success (the exact bug the operator hit).
    captured: dict = {}
    _patch_popen(monkeypatch, captured, [_INIT, _USER, _RESULT_ERROR])

    result = GeminiEngine().run(EngineRequest(directive="d", workdir=tmp_path))
    assert result.ok is False
    assert "Operation cancelled." in result.output_text


def test_run_tolerates_non_json_stdout_lines(tmp_path: Path, monkeypatch) -> None:
    # gemini prints plain warnings (e.g. the ripgrep fallback) between JSON events.
    captured: dict = {}
    noise = "Ripgrep is not available. Falling back to GrepTool."
    _patch_popen(monkeypatch, captured, [noise, _ASSISTANT_OK, _RESULT_SUCCESS])

    result = GeminiEngine().run(EngineRequest(directive="d", workdir=tmp_path))
    assert result.ok is True  # non-JSON line skipped, not fatal
