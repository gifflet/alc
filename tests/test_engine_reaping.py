# test_engine_reaping.py — the engine adapters must reap the WHOLE subprocess
# tree, not just the direct child.
#
# The bug (found by dogfooding): stopping or timing out a run killed only the
# `claude`/`gemini` child, leaving ITS descendants (Bash-tool processes, MCP
# servers) orphaned and still burning tokens. The fix spawns the engine in its
# own session (start_new_session=True) and signals the whole process GROUP on
# both the timeout and interrupt paths, via one shared helper (DRY).
from __future__ import annotations

import io
import signal
import threading
from pathlib import Path

import pytest

from alc.engine import EngineRequest
from alc.engines._proc import terminate_process_group
from alc.engines.claude_code import ClaudeCodeEngine
from alc.engines.gemini import GeminiEngine

# (Popen module to patch, engine class) — the shared reaping behaviour must hold
# for BOTH adapters, so every group-kill test runs against each.
_ENGINES = [
    ("alc.engines.claude_code", ClaudeCodeEngine),
    ("alc.engines.gemini", GeminiEngine),
]


# ---------------------------------------------------------------------------
# terminate_process_group — the shared helper
# ---------------------------------------------------------------------------


class _KillRecorder:
    """Minimal proc stand-in that records whether the bare-child fallback ran."""

    def __init__(self, pid: int = 4242) -> None:
        self.pid = pid
        self.kill_called = False

    def kill(self) -> None:
        self.kill_called = True


def test_terminate_kills_the_whole_group(monkeypatch: pytest.MonkeyPatch) -> None:
    # Happy path: the group led by the child's pid is SIGKILL'd; no bare-child fallback.
    proc = _KillRecorder(pid=4242)
    calls: dict = {}

    def fake_getpgid(pid: int) -> int:
        calls["getpgid"] = pid
        return 777

    def fake_killpg(pgid: int, sig: int) -> None:
        calls["killpg"] = (pgid, sig)

    monkeypatch.setattr("alc.engines._proc.os.getpgid", fake_getpgid)
    monkeypatch.setattr("alc.engines._proc.os.killpg", fake_killpg)

    terminate_process_group(proc)

    assert calls["getpgid"] == 4242
    assert calls["killpg"] == (777, signal.SIGKILL)
    assert proc.kill_called is False  # group kill succeeded — no fallback


def test_terminate_falls_back_when_getpgid_races(monkeypatch: pytest.MonkeyPatch) -> None:
    # The process already exited (getpgid -> ProcessLookupError): fall back to
    # proc.kill() and never raise.
    proc = _KillRecorder()

    def boom(_pid: int) -> int:
        raise ProcessLookupError

    monkeypatch.setattr("alc.engines._proc.os.getpgid", boom)

    terminate_process_group(proc)  # must not raise

    assert proc.kill_called is True


def test_terminate_falls_back_on_non_posix(monkeypatch: pytest.MonkeyPatch) -> None:
    # A platform without os.killpg (AttributeError) degrades to proc.kill().
    proc = _KillRecorder(pid=4242)
    monkeypatch.setattr("alc.engines._proc.os.getpgid", lambda _pid: 777)
    monkeypatch.delattr("alc.engines._proc.os.killpg", raising=False)

    terminate_process_group(proc)  # must not raise

    assert proc.kill_called is True


def test_terminate_never_raises_even_if_fallback_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Belt and braces: even if BOTH the group kill and the fallback fail, the
    # helper swallows it (it is called from timeout/interrupt paths that must
    # never explode).
    class _BadProc:
        pid = 4242

        def kill(self) -> None:
            raise ProcessLookupError

    def boom(_pid: int) -> int:
        raise ProcessLookupError

    monkeypatch.setattr("alc.engines._proc.os.getpgid", boom)

    terminate_process_group(_BadProc())  # must simply return


# ---------------------------------------------------------------------------
# Engines spawn in their own session
# ---------------------------------------------------------------------------


class _ClaudeDone:
    """A claude proc that streams one success result then EOF, exit 0."""

    def __init__(self) -> None:
        self.pid = 4242
        self.stdin = io.StringIO()
        self.stdout = io.StringIO('{"type":"result","subtype":"success","result":"done"}\n')
        self.stderr: list[str] = []
        self.returncode = 0

    def wait(self) -> int:
        return 0

    def kill(self) -> None:  # pragma: no cover - not the happy path
        pass


class _GeminiDone:
    """A gemini proc that streams one success result then EOF, exit 0."""

    def __init__(self) -> None:
        self.pid = 4242
        self.stdout = io.StringIO('{"type":"result","status":"success","response":"done","stats":{}}\n')
        self.stderr: list[str] = []
        self.returncode = 0

    def wait(self) -> int:
        return 0

    def kill(self) -> None:  # pragma: no cover - not the happy path
        pass


def test_claude_spawns_in_its_own_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict = {}

    def fake_popen(_cmd, **kwargs):
        captured.update(kwargs)
        return _ClaudeDone()

    monkeypatch.setattr("alc.engines.claude_code.subprocess.Popen", fake_popen)
    ClaudeCodeEngine().run(EngineRequest(directive="d", workdir=tmp_path, timeout_s=60))

    assert captured.get("start_new_session") is True


def test_gemini_spawns_in_its_own_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict = {}

    def fake_popen(_cmd, **kwargs):
        captured.update(kwargs)
        return _GeminiDone()

    monkeypatch.setattr("alc.engines.gemini.subprocess.Popen", fake_popen)
    GeminiEngine().run(EngineRequest(directive="d", workdir=tmp_path, timeout_s=60))

    assert captured.get("start_new_session") is True


# ---------------------------------------------------------------------------
# Timeout path reaps the group (not a bare proc.kill)
# ---------------------------------------------------------------------------


class _BlockingStdout:
    """readline() blocks until the group kill unblocks it, then reports EOF."""

    def __init__(self, unblock: threading.Event) -> None:
        self._unblock = unblock

    def readline(self) -> str:
        self._unblock.wait(timeout=3)
        return ""


class _BlockingProc:
    """A proc whose stdout hangs until it is reaped — drives the timeout path."""

    def __init__(self, unblock: threading.Event, pid: int = 4242) -> None:
        self.pid = pid
        self.stdin = io.StringIO()
        self.stdout = _BlockingStdout(unblock)
        self.stderr: list[str] = []
        self.returncode = -9
        self.kill_called = False

    def wait(self) -> int:
        return self.returncode

    def kill(self) -> None:
        self.kill_called = True


@pytest.mark.parametrize("popen_path,engine_cls", _ENGINES)
def test_timeout_reaps_the_process_group(
    popen_path: str, engine_cls, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    unblock = threading.Event()
    proc = _BlockingProc(unblock, pid=4242)
    monkeypatch.setattr(f"{popen_path}.subprocess.Popen", lambda *a, **k: proc)

    calls: dict = {}

    def fake_getpgid(pid: int) -> int:
        calls["getpgid"] = pid
        return 9999

    def fake_killpg(pgid: int, sig: int) -> None:
        calls["killpg"] = (pgid, sig)
        unblock.set()  # release the hung readline so the loop can finish

    monkeypatch.setattr("alc.engines._proc.os.getpgid", fake_getpgid)
    monkeypatch.setattr("alc.engines._proc.os.killpg", fake_killpg)

    result = engine_cls().run(
        EngineRequest(directive="d", workdir=tmp_path, timeout_s=0.05)
    )

    assert result.ok is False
    assert "timed out" in result.output_text
    assert calls["getpgid"] == 4242
    assert calls["killpg"] == (9999, signal.SIGKILL)  # the whole GROUP, not just the child
    assert proc.kill_called is False  # group kill succeeded — no bare-child fallback


# ---------------------------------------------------------------------------
# Interrupt path reaps the group, then propagates
# ---------------------------------------------------------------------------


class _InterruptStdout:
    """readline() raises KeyboardInterrupt — a Ctrl-C / stop during the read loop."""

    def readline(self) -> str:
        raise KeyboardInterrupt


class _InterruptProc:
    def __init__(self, pid: int = 4242) -> None:
        self.pid = pid
        self.stdin = io.StringIO()
        self.stdout = _InterruptStdout()
        self.stderr: list[str] = []
        self.returncode = None

    def wait(self) -> int:  # pragma: no cover - interrupt precedes wait
        return 0

    def kill(self) -> None:  # pragma: no cover - group kill is preferred
        pass


@pytest.mark.parametrize("popen_path,engine_cls", _ENGINES)
def test_interrupt_reaps_the_process_group_then_propagates(
    popen_path: str, engine_cls, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    proc = _InterruptProc(pid=4242)
    monkeypatch.setattr(f"{popen_path}.subprocess.Popen", lambda *a, **k: proc)

    calls: dict = {}
    monkeypatch.setattr("alc.engines._proc.os.getpgid", lambda _pid: 9999)

    def fake_killpg(pgid: int, sig: int) -> None:
        calls["killpg"] = (pgid, sig)

    monkeypatch.setattr("alc.engines._proc.os.killpg", fake_killpg)

    with pytest.raises(KeyboardInterrupt):
        engine_cls().run(EngineRequest(directive="d", workdir=tmp_path, timeout_s=60))

    # The tree was reaped BEFORE the interrupt propagated — no orphan left behind.
    assert calls["killpg"] == (9999, signal.SIGKILL)
