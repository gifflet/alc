# test_claude_code_failure.py — Hermetic tests for the claude-code adapter's
# failure reporting: a non-zero exit (or an error the CLI reports in its
# stream-json result event) must surface a CLEAR diagnostic — exit code + result
# subtype + the error text — not the old opaque "[claude-code] non-zero exit".
from __future__ import annotations

import io
from pathlib import Path

import pytest

from alc.engine import EngineRequest
from alc.engines.claude_code import ClaudeCodeEngine


class _FakeProc:
    """Minimal Popen stand-in: canned stdout stream-json + returncode + stderr."""

    def __init__(self, stdout: str, returncode: int, stderr: list[str] | None = None) -> None:
        self.stdin = io.StringIO()
        self.stdout = io.StringIO(stdout)
        self.stderr = stderr or []
        self.returncode = returncode

    def wait(self) -> int:
        return self.returncode

    def kill(self) -> None:  # pragma: no cover - timeout path not exercised here
        self.returncode = -9


def _run_with(monkeypatch, stdout: str, returncode: int, stderr=None):
    proc = _FakeProc(stdout, returncode, stderr)
    monkeypatch.setattr(
        "alc.engines.claude_code.subprocess.Popen", lambda *a, **k: proc
    )
    return ClaudeCodeEngine().run(
        EngineRequest(directive="do it", workdir=Path("."), timeout_s=60)
    )


def test_nonzero_exit_with_error_result_is_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    # The CLI died non-zero and reported the reason in its result event; the old
    # code returned "[claude-code] non-zero exit" (empty stderr) and threw the
    # result away. Now the exit code, subtype, and error text must all surface.
    stdout = (
        '{"type":"result","subtype":"error_during_execution",'
        '"is_error":true,"result":"Claude AI usage limit reached"}\n'
    )
    result = _run_with(monkeypatch, stdout, returncode=1, stderr=[])
    assert result.ok is False
    assert "exit 1" in result.output_text
    assert "error_during_execution" in result.output_text
    assert "usage limit" in result.output_text.lower()
    assert "non-zero exit" not in result.output_text  # no longer opaque


def test_error_result_on_zero_exit_is_still_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    # An error the CLI reports (is_error) must be a failure even if it exits 0.
    stdout = (
        '{"type":"result","subtype":"error_max_turns",'
        '"is_error":true,"result":"Reached max turns"}\n'
    )
    result = _run_with(monkeypatch, stdout, returncode=0)
    assert result.ok is False
    assert "error_max_turns" in result.output_text


def test_nonzero_exit_falls_back_to_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    # No result event on stdout, but stderr has the reason — surface it + the code.
    result = _run_with(
        monkeypatch, stdout="", returncode=127, stderr=["command not found: claude\n"]
    )
    assert result.ok is False
    assert "exit 127" in result.output_text
    assert "command not found" in result.output_text


def test_success_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    # A normal successful turn is byte-identical: ok True, output is the result text.
    stdout = '{"type":"result","subtype":"success","result":"done","total_cost_usd":0.01}\n'
    result = _run_with(monkeypatch, stdout, returncode=0)
    assert result.ok is True
    assert result.output_text == "done"
    assert result.usage.cost_usd == 0.01
