# test_claude_code_tools.py — the adapter persists each engine tool use to the run
# log (event "engine_activity", emitted by the shared ProgressPrinter) so the run
# detail can show WHAT the engine did — the Bash/Read/Edit/… activity — not just the
# control plane's macro events.
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from alc.engine import EngineRequest
from alc.engines.claude_code import ClaudeCodeEngine
from alc.events import bind_run_log


class _FakeProc:
    """Minimal Popen stand-in: canned stdout stream-json + returncode + stderr."""

    def __init__(self, stdout: str, returncode: int = 0) -> None:
        self.stdin = io.StringIO()
        self.stdout = io.StringIO(stdout)
        self.stderr: list[str] = []
        self.returncode = returncode

    def wait(self) -> int:
        return self.returncode

    def kill(self) -> None:  # pragma: no cover - timeout path not exercised
        self.returncode = -9


def test_tool_uses_are_emitted_to_the_run_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stdout = (
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Bash", "input": {"command": "grep -rn STEPS ."}},
                        {"type": "tool_use", "name": "Read", "input": {"file_path": "/app/src/foo.js"}},
                        {"type": "tool_use", "name": "Edit", "input": {"file_path": "/app/src/foo.js"}},
                    ]
                },
            }
        )
        + "\n"
        + json.dumps({"type": "result", "subtype": "success", "result": "done"})
        + "\n"
    )
    monkeypatch.setattr(
        "alc.engines.claude_code.subprocess.Popen", lambda *a, **k: _FakeProc(stdout)
    )

    log = tmp_path / "run.jsonl"
    with bind_run_log(log):
        result = ClaudeCodeEngine().run(
            EngineRequest(directive="do it", workdir=tmp_path, timeout_s=60)
        )

    assert result.ok is True
    events = [json.loads(ln) for ln in log.read_text().splitlines() if ln.strip()]
    tool_uses = [e["note"] for e in events if e.get("event") == "engine_activity"]
    assert tool_uses == [
        "Bash: grep -rn STEPS .",
        "Read: /app/src/foo.js",
        "Edit: /app/src/foo.js",
    ]


def test_no_run_log_bound_is_a_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # With no run log bound, emitting a tool use must not raise — the turn succeeds.
    stdout = (
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]},
            }
        )
        + "\n"
        + json.dumps({"type": "result", "subtype": "success", "result": "ok"})
        + "\n"
    )
    monkeypatch.setattr(
        "alc.engines.claude_code.subprocess.Popen", lambda *a, **k: _FakeProc(stdout)
    )
    result = ClaudeCodeEngine().run(
        EngineRequest(directive="do it", workdir=tmp_path, timeout_s=60)
    )
    assert result.ok is True
