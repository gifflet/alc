# test_runtime.py — the CORE-owned runtime harness (RuntimeService) and its
# execute_mandate wiring (service vs runtime-conventions vs nothing).
#
# Fully hermetic: no node, no real app. RuntimeService is exercised against a tiny
# inline Python http.server written to tmp_path; the execute_mandate wiring tests
# stub the harness with a fake context manager so no process is spawned.
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from alc.engine import Capabilities, EngineRequest, EngineResult
from alc.intake import load_manifest
from alc.models import Blueprint, Check, Manifest, ServiceSpec
from alc.runner import execute_mandate
from alc.runtime import RuntimeService
from alc.worktree import allocate_free_ports, release_ports

_MINIMAL_MANIFEST = Manifest(
    version=1,
    default_engine="mock",
    compute_tiers={"standard": {"mock": "mock-small"}},
    engines={"mock": {"type": "mock"}},
)


class _RecordingEngine:
    """Spy engine that records every EngineRequest it receives."""

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


# A tiny HTTP server that binds $PORT and answers 200 on /health. Written to
# tmp_path and launched via `python <script>` — no third-party dependency.
_HEALTHY_SERVER = """\
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass

HTTPServer(("127.0.0.1", int(os.environ["PORT"])), H).serve_forever()
"""


def _write_server(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "server.py"
    script.write_text(textwrap.dedent(body))
    return script


# ---------------------------------------------------------------------------
# RuntimeService unit — start, health poll, teardown, timeout
# ---------------------------------------------------------------------------


class TestRuntimeService:
    def test_healthy_server_yields_base_url_and_tears_down(self, tmp_path: Path) -> None:
        import urllib.request

        script = _write_server(tmp_path, _HEALTHY_SERVER)
        port = allocate_free_ports(1)[0]
        try:
            spec = ServiceSpec(start=f"python {script}", health="/health", ready_timeout_s=5)
            svc = RuntimeService(spec, tmp_path, port, {})
            base_url = svc.__enter__()
            try:
                assert base_url == f"http://127.0.0.1:{port}"
                # The health endpoint really answers 200 while inside the context.
                with urllib.request.urlopen(base_url + "/health", timeout=2) as resp:
                    assert resp.status == 200
                proc = svc._proc
            finally:
                svc.__exit__(None, None, None)
            # After __exit__ the process is gone.
            assert proc is not None
            assert proc.poll() is not None
        finally:
            release_ports([port])

    def test_never_healthy_raises_within_timeout_and_cleans_up(self, tmp_path: Path) -> None:
        # A server that never binds the health path -> health never returns 200.
        script = _write_server(
            tmp_path,
            """\
            import time
            time.sleep(60)
            """,
        )
        port = allocate_free_ports(1)[0]
        try:
            spec = ServiceSpec(start=f"python {script}", health="/health", ready_timeout_s=3)
            svc = RuntimeService(spec, tmp_path, port, {})
            with pytest.raises(RuntimeError, match="did not become healthy"):
                svc.__enter__()
            # The launched process was terminated during the failed __enter__.
            assert svc._proc is not None
            assert svc._proc.poll() is not None
        finally:
            release_ports([port])

    def test_process_exits_early_raises_with_output_tail(self, tmp_path: Path) -> None:
        # A start command that exits immediately (non-zero) -> fail fast, no waiting
        # for the full timeout, and the captured output tail is in the message.
        script = _write_server(
            tmp_path,
            """\
            import sys
            print("boom: could not start")
            sys.exit(1)
            """,
        )
        port = allocate_free_ports(1)[0]
        try:
            spec = ServiceSpec(start=f"python {script}", health="/health", ready_timeout_s=5)
            svc = RuntimeService(spec, tmp_path, port, {})
            with pytest.raises(RuntimeError, match="boom: could not start"):
                svc.__enter__()
        finally:
            release_ports([port])


# ---------------------------------------------------------------------------
# A fake harness so the wiring tests never spawn a process.
# ---------------------------------------------------------------------------


class _FakeRuntimeService:
    """Stand-in for RuntimeService: records nothing, spawns nothing."""

    entered = 0
    exited = 0

    def __init__(self, spec, workdir, port, env) -> None:
        self.port = port

    def __enter__(self) -> str:
        type(self).entered += 1
        return f"http://127.0.0.1:{self.port}"

    def __exit__(self, *exc) -> None:
        type(self).exited += 1


# ---------------------------------------------------------------------------
# execute_mandate wiring — service vs runtime-conventions vs nothing
# ---------------------------------------------------------------------------


def _bp(needs_service: bool = False) -> Blueprint:
    return Blueprint(
        name="qa",
        purpose="validate at runtime",
        checks=[Check(name="smoke", command=["true"])],
        workflow="# do it",
        needs_service=needs_service,
    )


class TestExecuteMandateServiceWiring:
    def _run(self, manifest, blueprint, operator_layer, tmp_path, monkeypatch, env):
        engine = _RecordingEngine()
        monkeypatch.setattr("alc.runner.resolve_engine", lambda name, cfg: engine)
        # Stub the harness so no real process is spawned.
        _FakeRuntimeService.entered = 0
        _FakeRuntimeService.exited = 0
        monkeypatch.setattr("alc.runner.RuntimeService", _FakeRuntimeService)
        execute_mandate(
            manifest=manifest,
            blueprint=blueprint,
            directive="# original",
            workdir=tmp_path,
            operator_layer=operator_layer,
            env=env,
        )
        return engine.received[0]

    def test_service_owned_exposes_base_url_and_service_conventions(
        self, monkeypatch, tmp_path: Path, operator_layer: Path
    ) -> None:
        manifest = load_manifest(operator_layer).model_copy(
            update={"service": ServiceSpec(start="python app.py")}
        )
        request = self._run(
            manifest, _bp(needs_service=True), operator_layer, tmp_path, monkeypatch, {}
        )
        # ALC allocated a port and exposed the base URL in the engine env.
        assert "ALC_BASE_URL" in request.env
        assert request.env["ALC_BASE_URL"].startswith("http://127.0.0.1:")
        assert "PORT" in request.env and "ALC_PORT" in request.env
        assert request.env["ALC_BASE_URL"] == f"http://127.0.0.1:{request.env['PORT']}"
        # The service-conventions prompt was appended, NOT runtime-conventions.
        assert "# original" in request.directive
        assert "Service conventions" in request.directive
        assert "$ALC_BASE_URL" in request.directive
        assert "Runtime conventions" not in request.directive
        # The harness ran for the loop and was torn down.
        assert _FakeRuntimeService.entered == 1
        assert _FakeRuntimeService.exited == 1

    def test_service_uses_injected_port_when_present(
        self, monkeypatch, tmp_path: Path, operator_layer: Path
    ) -> None:
        manifest = load_manifest(operator_layer).model_copy(
            update={"service": ServiceSpec(start="python app.py")}
        )
        request = self._run(
            manifest,
            _bp(needs_service=True),
            operator_layer,
            tmp_path,
            monkeypatch,
            {"ALC_PORT": "6123"},
        )
        assert request.env["ALC_BASE_URL"] == "http://127.0.0.1:6123"

    def test_needs_service_false_is_byte_identical(
        self, monkeypatch, tmp_path: Path, operator_layer: Path
    ) -> None:
        # Service declared on the manifest but the blueprint did NOT opt in ->
        # no ALC_BASE_URL, no service-conventions; no port -> directive untouched.
        manifest = load_manifest(operator_layer).model_copy(
            update={"service": ServiceSpec(start="python app.py")}
        )
        request = self._run(
            manifest, _bp(needs_service=False), operator_layer, tmp_path, monkeypatch, {}
        )
        assert "ALC_BASE_URL" not in request.env
        assert "Service conventions" not in request.directive
        assert request.directive == "# original"
        assert _FakeRuntimeService.entered == 0

    def test_manifest_service_none_is_byte_identical(
        self, monkeypatch, tmp_path: Path, operator_layer: Path
    ) -> None:
        # Blueprint opts in but the manifest has no service -> feature OFF.
        manifest = load_manifest(operator_layer)
        request = self._run(
            manifest, _bp(needs_service=True), operator_layer, tmp_path, monkeypatch, {}
        )
        assert "ALC_BASE_URL" not in request.env
        assert "Service conventions" not in request.directive
        assert request.directive == "# original"
        assert _FakeRuntimeService.entered == 0

    def test_bare_port_still_yields_runtime_conventions(
        self, monkeypatch, tmp_path: Path, operator_layer: Path
    ) -> None:
        # No service (blueprint doesn't opt in), but a port is present -> F1 path.
        manifest = load_manifest(operator_layer).model_copy(
            update={"service": ServiceSpec(start="python app.py")}
        )
        request = self._run(
            manifest,
            _bp(needs_service=False),
            operator_layer,
            tmp_path,
            monkeypatch,
            {"ALC_PORT": "5555"},
        )
        assert "Runtime conventions" in request.directive
        assert "Service conventions" not in request.directive
        assert "ALC_BASE_URL" not in request.env

    def test_no_port_no_service_directive_untouched(
        self, monkeypatch, tmp_path: Path, operator_layer: Path
    ) -> None:
        request = self._run(
            _MINIMAL_MANIFEST, _bp(needs_service=False), operator_layer, tmp_path, monkeypatch, {}
        )
        assert request.directive == "# original"
        assert request.env == {}


# ---------------------------------------------------------------------------
# The service-conventions reserved prompt
# ---------------------------------------------------------------------------


def test_service_conventions_is_a_reserved_prompt(operator_layer: Path) -> None:
    from alc.prompts import resolve_prompt

    text = resolve_prompt(
        "service-conventions", operator_layer, load_manifest(operator_layer)
    )
    assert "Service conventions" in text
    assert "$ALC_BASE_URL" in text
