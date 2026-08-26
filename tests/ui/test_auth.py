# test_auth.py — The optional bearer-token gate.
#
# The load-bearing property is the DEFAULT: with no token configured the server
# must behave exactly as it always has. Every other test in tests/ui/ relies on
# that, so auth cannot become mandatory by accident.
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from alc.ui.auth import WS_UNAUTHORIZED, bearer_from_header, token_matches
from alc.ui.server import create_app

TOKEN = "s3cret-token"


@pytest.fixture
def secure_app(registry_path: Path):
    return create_app(registry_path, enable_watch=False, token=TOKEN)


@pytest.fixture
def secure_client(secure_app):
    with TestClient(secure_app) as client:
        yield client


class TestTokenHelpers:
    def test_no_configured_token_allows_anything(self) -> None:
        assert token_matches(None, None) is True
        assert token_matches("", "whatever") is True

    def test_requires_an_exact_match(self) -> None:
        assert token_matches(TOKEN, TOKEN) is True
        assert token_matches(TOKEN, "wrong") is False
        assert token_matches(TOKEN, None) is False
        assert token_matches(TOKEN, TOKEN + "x") is False

    def test_parses_only_the_bearer_scheme(self) -> None:
        assert bearer_from_header(f"Bearer {TOKEN}") == TOKEN
        assert bearer_from_header(f"bearer {TOKEN}") == TOKEN
        assert bearer_from_header(f"Basic {TOKEN}") is None
        assert bearer_from_header("Bearer   ") is None
        assert bearer_from_header(None) is None


class TestUnauthenticatedDefault:
    """No token configured -> byte-identical to the behaviour before this change."""

    def test_api_needs_no_header(self, client) -> None:
        assert client.get("/api/projects").status_code == 200

    def test_ws_needs_no_auth_frame(self, client, registered: str) -> None:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "subscribe", "project_id": registered})
            assert ws.receive_json() == {"type": "subscribed", "project_id": registered}


class TestAuthenticated:
    def test_api_without_a_token_is_401(self, secure_client) -> None:
        assert secure_client.get("/api/projects").status_code == 401

    def test_api_with_a_wrong_token_is_401(self, secure_client) -> None:
        resp = secure_client.get("/api/projects", headers={"Authorization": "Bearer nope"})
        assert resp.status_code == 401

    def test_api_with_the_token_succeeds(self, secure_client) -> None:
        resp = secure_client.get("/api/projects", headers={"Authorization": f"Bearer {TOKEN}"})
        assert resp.status_code == 200

    def test_every_project_route_is_gated_not_just_the_first(
        self, secure_client, project: Path
    ) -> None:
        # Register through the authenticated door, then probe a spread of routers.
        created = secure_client.post(
            "/api/projects",
            json={"path": str(project)},
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert created.status_code == 201
        pid = created.json()["id"]
        for path in (
            f"/api/projects/{pid}/queue",
            f"/api/projects/{pid}/fleet",
            f"/api/projects/{pid}/branches",
            f"/api/projects/{pid}/manifest",
            f"/api/projects/{pid}/blueprints",
        ):
            assert secure_client.get(path).status_code == 401, path
            ok = secure_client.get(path, headers={"Authorization": f"Bearer {TOKEN}"})
            assert ok.status_code == 200, path

    def test_the_spa_shell_stays_reachable_so_it_can_ask_for_a_token(
        self, registry_path: Path, tmp_path: Path
    ) -> None:
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<!doctype html><title>alc</title>")
        app = create_app(registry_path, ui_dist=dist, enable_watch=False, token=TOKEN)
        with TestClient(app) as client:
            assert client.get("/").status_code == 200

    def test_ws_without_an_auth_frame_is_closed_with_4401(
        self, secure_client, registered_secure: str
    ) -> None:
        with secure_client.websocket_connect("/ws") as ws:
            # A subscribe that skips the auth frame must not be honoured.
            ws.send_json({"type": "subscribe", "project_id": registered_secure})
            with pytest.raises(WebSocketDisconnect) as excinfo:
                ws.receive_json()
        assert excinfo.value.code == WS_UNAUTHORIZED

    def test_ws_with_a_bad_token_is_closed_with_4401(self, secure_client) -> None:
        with secure_client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "auth", "token": "nope"})
            with pytest.raises(WebSocketDisconnect) as excinfo:
                ws.receive_json()
        assert excinfo.value.code == WS_UNAUTHORIZED

    def test_ws_with_the_token_subscribes_as_usual(
        self, secure_client, registered_secure: str
    ) -> None:
        with secure_client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "auth", "token": TOKEN})
            ws.send_json({"type": "subscribe", "project_id": registered_secure})
            assert ws.receive_json() == {"type": "subscribed", "project_id": registered_secure}


@pytest.fixture
def registered_secure(secure_client, project: Path) -> str:
    resp = secure_client.post(
        "/api/projects",
        json={"path": str(project)},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_browse_is_behind_the_token(secure_client) -> None:
    """Filesystem browsing widens what the API can read — from one project's
    files to any directory on the host — so it must not be the one route that
    skips the guard."""
    assert secure_client.get("/api/fs/browse").status_code == 401
    ok = secure_client.get("/api/fs/browse", headers={"Authorization": f"Bearer {TOKEN}"})
    assert ok.status_code == 200
