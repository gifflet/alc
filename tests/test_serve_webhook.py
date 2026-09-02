# test_serve_webhook.py — Hermetic tests for
# `alc serve --webhook`, the stdlib-`http.server` door onto signal intake
# (`signals.ingest`) and the enqueue path (`conduct.dispatch_enqueue`).
#
# Never binds a public interface or a fixed port: every server in this file
# binds 127.0.0.1:0 (loopback, OS-assigned ephemeral port) via `webhook.serve`,
# run in a background thread, and is shut down at fixture teardown.
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

from alc.intake import load_manifest
from alc.models import QueueTask
from alc.signals import read_signals
from alc.webhook import serve


# ---------------------------------------------------------------------------
# A tiny loopback HTTP client + the webhook_server fixture
# ---------------------------------------------------------------------------


class _Client:
    """Minimal urllib-based client: returns (status, parsed-json-body) always,
    HTTPError included (a 4xx/5xx raises in urllib; this normalizes it)."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url

    def _request(
        self, method: str, path: str, body: bytes | None, headers: dict
    ) -> tuple[int, dict]:
        req = urllib.request.Request(
            self._base_url + path, data=body, method=method, headers=headers
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def get(self, path: str, headers: dict | None = None) -> tuple[int, dict]:
        return self._request("GET", path, None, headers or {})

    def post_json(
        self, path: str, payload: dict, headers: dict | None = None
    ) -> tuple[int, dict]:
        body = json.dumps(payload).encode()
        hdrs = {"Content-Type": "application/json", **(headers or {})}
        return self._request("POST", path, body, hdrs)

    def post_raw(
        self, path: str, raw: bytes, headers: dict | None = None
    ) -> tuple[int, dict]:
        hdrs = {"Content-Type": "application/json", **(headers or {})}
        return self._request("POST", path, raw, hdrs)


@pytest.fixture
def webhook_server(operator_layer: Path):
    """Factory fixture: `webhook_server(token=None)` boots a webhook server bound
    to the `operator_layer` fixture's Operator Layer and returns a `_Client`.
    Every server started is shut down at teardown."""
    manifest = load_manifest(operator_layer)
    started: list = []

    def factory(token: str | None = None) -> _Client:
        server = serve("127.0.0.1", 0, operator_layer, manifest, token)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        started.append(server)
        return _Client(f"http://127.0.0.1:{server.server_port}")

    yield factory

    for server in started:
        server.shutdown()
        server.server_close()


def _pending_queue_files(operator_layer: Path) -> list[Path]:
    manifest = load_manifest(operator_layer)
    queue_dir = operator_layer.parent / manifest.queue_dir
    return sorted(queue_dir.glob("*.yaml")) if queue_dir.is_dir() else []


def _pending_signals(operator_layer: Path):
    manifest = load_manifest(operator_layer)
    return read_signals(operator_layer.parent / manifest.signals_dir)


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


class TestHealth:
    def test_returns_200_without_a_token(
        self, webhook_server, operator_layer: Path
    ) -> None:
        client = webhook_server()

        status, body = client.get("/health")

        assert status == 200
        assert body == {"status": "ok"}

    def test_does_not_require_a_token_even_when_one_is_configured(
        self, webhook_server
    ) -> None:
        client = webhook_server(token="secret")

        status, _ = client.get("/health")

        assert status == 200


# ---------------------------------------------------------------------------
# POST /signal
# ---------------------------------------------------------------------------


class TestSignalEndpoint:
    def test_valid_signal_returns_201_and_writes_a_file(
        self, webhook_server, operator_layer: Path
    ) -> None:
        client = webhook_server()

        status, body = client.post_json(
            "/signal",
            {
                "kind": "error",
                "source": "sentry",
                "title": "NullPointerException in checkout",
                "body": "Traceback...",
                "ts": 100.0,
            },
        )

        assert status == 201
        assert "path" in body
        [pending] = _pending_signals(operator_layer)
        assert pending.signal.kind == "error"
        assert pending.signal.source == "sentry"
        assert pending.signal.title == "NullPointerException in checkout"

    def test_realistic_external_payload_with_no_ts_defaults_to_now(
        self, webhook_server, operator_layer: Path
    ) -> None:
        """The webhook exists to receive payloads FROM external systems (a
        Sentry alert, a GitHub issue hook, a review-comment webhook) — none of
        which knows or should know about ALC's internal `ts` field. A payload
        that omits it must still be accepted, `ts` defaulting to now exactly
        like `alc signal ingest` already does for a `--from-file` payload."""
        before = time.time()
        client = webhook_server()

        status, body = client.post_json(
            "/signal",
            {"kind": "error", "source": "sentry", "title": "boom"},
        )
        after = time.time()

        assert status == 201
        assert "path" in body
        [pending] = _pending_signals(operator_layer)
        assert before <= pending.signal.ts <= after

    def test_a_ts_the_caller_sends_is_kept_exactly_not_overridden(
        self, webhook_server, operator_layer: Path
    ) -> None:
        client = webhook_server()

        status, _ = client.post_json(
            "/signal",
            {"kind": "error", "source": "sentry", "title": "boom", "ts": 12345.0},
        )

        assert status == 201
        [pending] = _pending_signals(operator_layer)
        assert pending.signal.ts == 12345.0

    def test_invalid_kind_is_400_and_writes_nothing(
        self, webhook_server, operator_layer: Path
    ) -> None:
        client = webhook_server()

        status, body = client.post_json(
            "/signal",
            {"kind": "rumor", "source": "x", "title": "y", "ts": 1.0},
        )

        assert 400 <= status < 500
        assert "error" in body
        assert _pending_signals(operator_layer) == []

    def test_missing_required_field_is_400_and_writes_nothing(
        self, webhook_server, operator_layer: Path
    ) -> None:
        client = webhook_server()

        status, _ = client.post_json("/signal", {"kind": "error", "source": "x"})

        assert 400 <= status < 500
        assert _pending_signals(operator_layer) == []

    def test_garbage_bytes_are_a_clean_400_not_a_traceback(
        self, webhook_server, operator_layer: Path
    ) -> None:
        client = webhook_server()

        status, body = client.post_raw("/signal", b"{not json at all")

        assert status == 400
        assert "error" in body
        assert _pending_signals(operator_layer) == []


# ---------------------------------------------------------------------------
# POST /enqueue
# ---------------------------------------------------------------------------


class TestEnqueueEndpoint:
    def test_valid_flow_task_returns_201_and_writes_a_queue_file(
        self, webhook_server, operator_layer: Path
    ) -> None:
        client = webhook_server()

        status, body = client.post_json(
            "/enqueue", {"flow": "ship", "task": "do the thing"}
        )

        assert status == 201
        assert "file" in body
        [pending] = _pending_queue_files(operator_layer)
        qt = QueueTask.model_validate(yaml.safe_load(pending.read_text()))
        assert qt.flow == "ship"
        assert qt.task == "do the thing"
        assert qt.isolate is True

    def test_specialist_task_carries_kind_and_name(
        self, webhook_server, operator_layer: Path
    ) -> None:
        client = webhook_server()

        status, _ = client.post_json(
            "/enqueue",
            {"kind": "specialist", "name": "db", "task": "fix the migration"},
        )

        assert status == 201
        [pending] = _pending_queue_files(operator_layer)
        qt = QueueTask.model_validate(yaml.safe_load(pending.read_text()))
        assert qt.kind == "specialist"
        assert qt.name == "db"

    def test_engine_isolate_priority_and_depends_on_are_carried_through(
        self, webhook_server, operator_layer: Path
    ) -> None:
        client = webhook_server()

        status, _ = client.post_json(
            "/enqueue",
            {
                "flow": "ship",
                "task": "do the thing",
                "engine": "mock",
                "isolate": False,
                "priority": 5,
                "id": "t1",
            },
        )

        assert status == 201
        [pending] = _pending_queue_files(operator_layer)
        qt = QueueTask.model_validate(yaml.safe_load(pending.read_text()))
        assert qt.engine == "mock"
        assert qt.isolate is False
        assert qt.priority == 5
        assert qt.id == "t1"

    def test_missing_task_field_is_400_and_writes_nothing(
        self, webhook_server, operator_layer: Path
    ) -> None:
        client = webhook_server()

        status, body = client.post_json("/enqueue", {"flow": "ship"})

        assert 400 <= status < 500
        assert "error" in body
        assert _pending_queue_files(operator_layer) == []

    def test_invalid_kind_is_400_and_writes_nothing(
        self, webhook_server, operator_layer: Path
    ) -> None:
        client = webhook_server()

        status, _ = client.post_json(
            "/enqueue", {"kind": "bogus", "task": "x"}
        )

        assert 400 <= status < 500
        assert _pending_queue_files(operator_layer) == []

    def test_garbage_bytes_are_a_clean_400_not_a_traceback(
        self, webhook_server, operator_layer: Path
    ) -> None:
        client = webhook_server()

        status, body = client.post_raw("/enqueue", b"\xff\xfe not json")

        assert status == 400
        assert "error" in body
        assert _pending_queue_files(operator_layer) == []

    def test_json_array_instead_of_object_is_400(
        self, webhook_server, operator_layer: Path
    ) -> None:
        client = webhook_server()

        status, _ = client.post_raw("/enqueue", b"[1, 2, 3]")

        assert 400 <= status < 500
        assert _pending_queue_files(operator_layer) == []


# ---------------------------------------------------------------------------
# Unknown paths
# ---------------------------------------------------------------------------


class TestUnknownPath:
    def test_unknown_get_path_is_404(self, webhook_server) -> None:
        client = webhook_server()

        status, body = client.get("/nope")

        assert status == 404
        assert "error" in body

    def test_unknown_post_path_is_404(self, webhook_server) -> None:
        client = webhook_server()

        status, _ = client.post_json("/other", {"a": 1})

        assert status == 404


# ---------------------------------------------------------------------------
# Token authorization
# ---------------------------------------------------------------------------


class TestTokenAuthorization:
    def test_missing_token_is_401_when_one_is_configured(
        self, webhook_server, operator_layer: Path
    ) -> None:
        client = webhook_server(token="secret")

        status, body = client.post_json("/enqueue", {"flow": "ship", "task": "x"})

        assert status == 401
        assert "error" in body
        assert _pending_queue_files(operator_layer) == []

    def test_wrong_token_is_401(self, webhook_server, operator_layer: Path) -> None:
        client = webhook_server(token="secret")

        status, _ = client.post_json(
            "/enqueue",
            {"flow": "ship", "task": "x"},
            headers={"Authorization": "Bearer wrong"},
        )

        assert status == 401
        assert _pending_queue_files(operator_layer) == []

    def test_correct_token_is_accepted(
        self, webhook_server, operator_layer: Path
    ) -> None:
        client = webhook_server(token="secret")

        status, _ = client.post_json(
            "/enqueue",
            {"flow": "ship", "task": "x"},
            headers={"Authorization": "Bearer secret"},
        )

        assert status == 201
        assert len(_pending_queue_files(operator_layer)) == 1

    def test_no_token_configured_accepts_unauthenticated_requests(
        self, webhook_server
    ) -> None:
        client = webhook_server(token=None)

        status, _ = client.post_json("/enqueue", {"flow": "ship", "task": "x"})

        assert status == 201

    def test_no_token_configured_warns_on_stderr(
        self, operator_layer: Path, capsys
    ) -> None:
        manifest = load_manifest(operator_layer)

        server = serve("127.0.0.1", 0, operator_layer, manifest, None)
        try:
            err = capsys.readouterr().err
            assert "WARN" in err
            assert "unauthenticated" in err.lower() or "token" in err.lower()
        finally:
            server.server_close()

    def test_setting_a_token_prints_no_warning(
        self, operator_layer: Path, capsys
    ) -> None:
        manifest = load_manifest(operator_layer)

        server = serve("127.0.0.1", 0, operator_layer, manifest, "secret")
        try:
            err = capsys.readouterr().err
            assert err == ""
        finally:
            server.server_close()


# ---------------------------------------------------------------------------
# The server never runs an engine turn — it only ever writes.
# ---------------------------------------------------------------------------


class TestNeverExecutesAnEngineTurn:
    def test_enqueue_leaves_the_task_pending_never_drained(
        self, webhook_server, operator_layer: Path
    ) -> None:
        client = webhook_server()

        status, _ = client.post_json(
            "/enqueue", {"flow": "ship", "task": "do the thing"}
        )

        assert status == 201
        manifest = load_manifest(operator_layer)
        queue_dir = operator_layer.parent / manifest.queue_dir
        assert len(_pending_queue_files(operator_layer)) == 1
        # A drained/executed task would be archived under done/ with a report;
        # neither exists — nothing but the plain queue write ever happened.
        assert not (queue_dir / "done").exists()

    def test_signal_is_left_pending_never_consumed_into_a_demand(
        self, webhook_server, operator_layer: Path
    ) -> None:
        client = webhook_server()

        status, _ = client.post_json(
            "/signal",
            {"kind": "issue", "source": "linear", "title": "t", "ts": 1.0},
        )

        assert status == 201
        assert len(_pending_signals(operator_layer)) == 1
        # A "signals" replenish consuming it would enqueue a demand and archive
        # the signal into signals_dir/done/ — neither happened.
        assert _pending_queue_files(operator_layer) == []
        manifest = load_manifest(operator_layer)
        signals_dir = operator_layer.parent / manifest.signals_dir
        assert not (signals_dir / "done").exists()
