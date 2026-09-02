# webhook.py — a minimal HTTP door in front of the
# signal intake (`signals.ingest`) and the enqueue path (`conduct.dispatch_enqueue`),
# both of which already write to disk without an engine turn (Wave 1, phase-5).
#
# Built on the stdlib `http.server` — not the `ui` extra's fastapi/uvicorn —
# so `alc serve --webhook` never drags in an optional dependency. CORE module:
# must not import `alc.ui`.
#
# It never executes anything: POST /signal and POST /enqueue only validate a
# payload (through the real Signal / QueueTask pydantic models) and materialize
# it as a file — a signal JSON or a queue task YAML. `alc tick` / `alc cycle`
# drains the queue later, on its own turn. A bad payload answers 4xx and writes
# nothing, so the queue/signals dirs never see a malformed file.
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from pydantic import ValidationError

from alc.conduct import dispatch_enqueue
from alc.models import ConductorPlan, Manifest, PlannedUnit, QueueTask, Signal
from alc.signals import ingest as ingest_signal


def _write_queue_task(qt: QueueTask, manifest: Manifest, operator_layer: Path) -> str:
    """Materialize *qt* through `dispatch_enqueue` — the exact helper `cmd_enqueue`
    calls — so the webhook writes queue files byte-shape-identical to `alc enqueue`
    (no second enqueue path). Returns the written filename.
    """
    unit = PlannedUnit(
        kind=qt.kind,
        name=qt.unit_name(),
        task=qt.task,
        id=qt.id,
        depends_on=qt.depends_on,
    )
    [filename] = dispatch_enqueue(
        ConductorPlan(items=[unit]),
        manifest,
        operator_layer,
        engine_override=qt.engine,
        isolate=qt.isolate,
        prefix="webhook",
        priority=qt.priority,
    )
    return filename


def make_handler(
    operator_layer: Path, manifest: Manifest, token: str | None
) -> type[BaseHTTPRequestHandler]:
    """Build a `BaseHTTPRequestHandler` subclass bound to *operator_layer* / *manifest*
    / *token* — a class, not an instance, because `HTTPServer` instantiates one
    handler per request (the stdlib's own pattern). Kept synchronous and
    self-contained: no threading here, no engine turn, ever.
    """

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, status: int, body: dict) -> None:
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _authorized(self) -> bool:
            if token is None:
                return True
            return self.headers.get("Authorization") == f"Bearer {token}"

        def _read_json_body(self) -> tuple[dict | None, str | None]:
            """Return (body, None) on success, or (None, error) — never raises on
            garbage bytes or a non-object JSON value."""
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                data = json.loads(raw) if raw else {}
            except ValueError as exc:
                # json.JSONDecodeError (malformed JSON) and UnicodeDecodeError
                # (json.loads sniffing a BOM in arbitrary bytes, e.g. b"\xff\xfe...")
                # are both ValueError subclasses — either way, a clean 400.
                return None, f"invalid JSON: {exc}"
            if not isinstance(data, dict):
                return None, "body must be a JSON object"
            return data, None

        def do_GET(self) -> None:  # noqa: N802 (stdlib handler method name)
            if self.path == "/health":
                self._reply(200, {"status": "ok"})
                return
            self._reply(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802 (stdlib handler method name)
            if self.path not in ("/signal", "/enqueue"):
                self._reply(404, {"error": "not found"})
                return
            if not self._authorized():
                self._reply(401, {"error": "unauthorized"})
                return

            data, err = self._read_json_body()
            if err is not None:
                self._reply(400, {"error": err})
                return

            if self.path == "/signal":
                try:
                    signal = Signal.model_validate(data)
                except ValidationError as exc:
                    self._reply(400, {"error": str(exc)})
                    return
                signals_dir = operator_layer.parent / manifest.signals_dir
                path = ingest_signal(signals_dir, signal)
                self._reply(201, {"path": str(path)})
                return

            # POST /enqueue
            try:
                qt = QueueTask.model_validate(data)
            except ValidationError as exc:
                self._reply(400, {"error": str(exc)})
                return
            filename = _write_queue_task(qt, manifest, operator_layer)
            self._reply(201, {"file": filename})

        def log_message(self, *args: object) -> None:
            pass  # keep webhook traffic off stderr; the CLI has its own conventions

    return Handler


def serve(
    host: str, port: int, operator_layer: Path, manifest: Manifest, token: str | None
) -> HTTPServer:
    """Bind and return a ready `HTTPServer` — the caller drives `serve_forever()` /
    `shutdown()` (mirrors `cmd_ui`'s relationship to `uvicorn.run`). Returning the
    bound-but-not-looping server (rather than blocking here) is what lets a test
    bind an ephemeral port (``port=0``) and read the OS-assigned ``server_port``
    before starting the loop in a background thread.

    When *token* is None, warns on stderr: an unauthenticated webhook must never
    open a port wide without the operator being told.
    """
    if token is None:
        print(
            "[WARN] alc serve --webhook: no --token set — this port accepts "
            "unauthenticated requests from anyone who can reach it.",
            file=sys.stderr,
        )
    handler = make_handler(operator_layer, manifest, token)
    return HTTPServer((host, port), handler)
