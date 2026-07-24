# test_signals_api.py — GET /signals and POST /signals (ingest).
from __future__ import annotations

from pathlib import Path


class TestListSignals:
    def test_no_pending_signals_is_an_empty_list(self, client, registered: str) -> None:
        resp = client.get(f"/api/projects/{registered}/signals")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_lists_a_previously_ingested_signal(self, client, registered: str) -> None:
        client.post(
            f"/api/projects/{registered}/signals",
            json={"kind": "error", "source": "sentry", "title": "NPE in checkout"},
        )

        resp = client.get(f"/api/projects/{registered}/signals")
        assert resp.status_code == 200
        [signal] = resp.json()
        assert signal["kind"] == "error"
        assert signal["source"] == "sentry"
        assert signal["title"] == "NPE in checkout"


class TestIngestSignal:
    def test_writes_a_signal_file_under_signals_dir(
        self, client, registered: str, project: Path
    ) -> None:
        resp = client.post(
            f"/api/projects/{registered}/signals",
            json={"kind": "feedback", "source": "operator", "title": "slow onboarding"},
        )
        assert resp.status_code == 201
        path = Path(resp.json()["path"])
        assert path.is_file()
        assert path.parent == project / ".alc" / "signals"

    def test_ts_defaults_to_now_when_omitted(self, client, registered: str) -> None:
        resp = client.post(
            f"/api/projects/{registered}/signals",
            json={"kind": "issue", "source": "github", "title": "bug"},
        )
        assert resp.status_code == 201
        [signal] = client.get(f"/api/projects/{registered}/signals").json()
        assert signal["ts"] > 0

    def test_ts_is_kept_when_given(self, client, registered: str) -> None:
        resp = client.post(
            f"/api/projects/{registered}/signals",
            json={"kind": "issue", "source": "github", "title": "bug", "ts": 12345.0},
        )
        assert resp.status_code == 201
        [signal] = client.get(f"/api/projects/{registered}/signals").json()
        assert signal["ts"] == 12345.0

    def test_invalid_kind_is_422(self, client, registered: str) -> None:
        resp = client.post(
            f"/api/projects/{registered}/signals",
            json={"kind": "not-a-real-kind", "source": "x", "title": "y"},
        )
        assert resp.status_code == 422

    def test_publishes_a_signals_changed_ws_event(self, client, registered: str) -> None:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "subscribe", "project_id": registered})
            assert ws.receive_json()["type"] == "subscribed"

            resp = client.post(
                f"/api/projects/{registered}/signals",
                json={"kind": "review", "source": "github", "title": "nit"},
            )
            assert resp.status_code == 201

            message = ws.receive_json()
            assert message["type"] == "signals_changed"
            assert message["project_id"] == registered
