# Hermetic tests for the claude-code engine's opt-in clean_config mode.
# These do NOT invoke the real `claude` binary: subprocess.Popen is monkeypatched
# to capture the argv the adapter builds, then feed back a single stream-json
# `result` event so run() completes normally without any model call.
from __future__ import annotations

import io
from pathlib import Path

import pytest

from alc.engine import EngineRequest
from alc.engines.claude_code import ClaudeCodeEngine
from alc.engines.registry import resolve_engine


class _FakeProc:
    """Minimal stand-in for a Popen object satisfying ClaudeCodeEngine.run()."""

    def __init__(self) -> None:
        self.stdin = io.StringIO()
        # One stream-json result event, then EOF (readline returns "").
        self.stdout = io.StringIO('{"type": "result", "result": "done"}\n')
        self.stderr: list[str] = []
        self.returncode = 0

    def wait(self) -> int:
        return 0

    def kill(self) -> None:  # pragma: no cover - timeout path not exercised
        self.returncode = -9


def _capture_argv(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Patch subprocess.Popen in the adapter to record argv without executing."""
    captured: list[list[str]] = []

    def _fake_popen(cmd: list[str], *args: object, **kwargs: object) -> _FakeProc:
        captured.append(list(cmd))
        return _FakeProc()

    monkeypatch.setattr("alc.engines.claude_code.subprocess.Popen", _fake_popen)
    return captured


def _run(engine: ClaudeCodeEngine, tmp_path: Path) -> None:
    engine.run(EngineRequest(directive="hi", workdir=tmp_path, timeout_s=5))


def test_clean_config_appends_setting_sources_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """clean_config=True restricts setting sources to user,local (skips project)."""
    captured = _capture_argv(monkeypatch)
    _run(ClaudeCodeEngine(clean_config=True), tmp_path)

    argv = captured[0]
    assert "--setting-sources" in argv
    assert argv[argv.index("--setting-sources") + 1] == "user,local"


def test_default_argv_omits_the_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Default (clean_config=False) leaves the argv unchanged — no new flag."""
    captured = _capture_argv(monkeypatch)
    _run(ClaudeCodeEngine(), tmp_path)

    assert "--setting-sources" not in captured[0]


def test_registry_reads_clean_config_from_manifest_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The registry threads the manifest's clean_config into the adapter argv."""
    engine = resolve_engine(
        "claude-code",
        {"claude-code": {"type": "claude-code", "clean_config": True}},
    )
    assert isinstance(engine, ClaudeCodeEngine)

    captured = _capture_argv(monkeypatch)
    _run(engine, tmp_path)
    assert "--setting-sources" in captured[0]


def test_registry_defaults_clean_config_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without the key, the registry constructs the adapter with clean_config off."""
    engine = resolve_engine(
        "claude-code",
        {"claude-code": {"type": "claude-code", "binary": "claude"}},
    )

    captured = _capture_argv(monkeypatch)
    _run(engine, tmp_path)
    assert "--setting-sources" not in captured[0]
