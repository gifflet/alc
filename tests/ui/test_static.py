# test_static.py — SPA static serving, frontend resolution chain and `alc ui`.
from __future__ import annotations

import argparse
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alc.cli import cmd_ui
from alc.ui.frontend import FrontendError, resolve_frontend
from alc.ui.server import create_app


def _make_dist(base: Path, name: str = "dist") -> Path:
    dist = base / name
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text("<!doctype html><title>alc ui</title>")
    (dist / "app.js").write_text("console.log('ui')")
    return dist


# ---------------------------------------------------------------------------
# SPA static serving
# ---------------------------------------------------------------------------


class TestSpaStatic:
    def test_root_serves_index(self, tmp_path: Path) -> None:
        app = create_app(tmp_path / "registry.json", ui_dist=_make_dist(tmp_path), enable_watch=False)
        with TestClient(app) as client:
            resp = client.get("/")
            assert resp.status_code == 200
            assert "alc ui" in resp.text

    def test_unknown_route_falls_back_to_index(self, tmp_path: Path) -> None:
        app = create_app(tmp_path / "registry.json", ui_dist=_make_dist(tmp_path), enable_watch=False)
        with TestClient(app) as client:
            resp = client.get("/dashboard/anything")
            assert resp.status_code == 200
            assert "alc ui" in resp.text

    def test_static_asset_served(self, tmp_path: Path) -> None:
        app = create_app(tmp_path / "registry.json", ui_dist=_make_dist(tmp_path), enable_watch=False)
        with TestClient(app) as client:
            resp = client.get("/app.js")
            assert resp.status_code == 200
            assert "console.log" in resp.text

    def test_api_takes_precedence_over_spa(self, tmp_path: Path) -> None:
        app = create_app(tmp_path / "registry.json", ui_dist=_make_dist(tmp_path), enable_watch=False)
        with TestClient(app) as client:
            resp = client.get("/api/projects")
            assert resp.status_code == 200
            assert resp.json() == []

    def test_no_dist_means_api_only(self, tmp_path: Path) -> None:
        app = create_app(tmp_path / "registry.json", enable_watch=False)
        with TestClient(app) as client:
            assert client.get("/").status_code == 404
            assert client.get("/api/projects").status_code == 200

    def test_http_get_on_ws_is_not_served_as_spa(self, tmp_path: Path) -> None:
        # A downgraded WebSocket upgrade (plain HTTP GET) must NOT get index.html;
        # otherwise the browser sees "Unexpected response code: 200" on /ws.
        app = create_app(tmp_path / "registry.json", ui_dist=_make_dist(tmp_path), enable_watch=False)
        with TestClient(app) as client:
            resp = client.get("/ws")
            assert resp.status_code == 404
            assert "alc ui" not in resp.text

    def test_ws_connects_with_spa_mounted(self, tmp_path: Path) -> None:
        app = create_app(tmp_path / "registry.json", ui_dist=_make_dist(tmp_path), enable_watch=False)
        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
                ws.send_json({"type": "subscribe", "project_id": "x"})
                assert ws.receive_json() == {"type": "subscribed", "project_id": "x"}

    def test_unknown_api_route_not_served_as_spa(self, tmp_path: Path) -> None:
        app = create_app(tmp_path / "registry.json", ui_dist=_make_dist(tmp_path), enable_watch=False)
        with TestClient(app) as client:
            resp = client.get("/api/does-not-exist")
            assert resp.status_code == 404
            assert "alc ui" not in resp.text


# ---------------------------------------------------------------------------
# Frontend resolution chain: flag > env > bundled > none
# ---------------------------------------------------------------------------


class TestResolveFrontend:
    def test_explicit_flag_wins(self, tmp_path: Path) -> None:
        flag = _make_dist(tmp_path, "flag")
        env = _make_dist(tmp_path, "env")
        assert resolve_frontend(str(flag), str(env), bundled=tmp_path / "bundled") == flag

    def test_explicit_flag_missing_index_raises(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(FrontendError):
            resolve_frontend(str(empty), None, bundled=tmp_path / "bundled")

    def test_explicit_flag_missing_path_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FrontendError):
            resolve_frontend(str(tmp_path / "ghost"), None, bundled=tmp_path / "bundled")

    def test_env_used_when_no_flag(self, tmp_path: Path) -> None:
        env = _make_dist(tmp_path, "env")
        assert resolve_frontend(None, str(env), bundled=tmp_path / "bundled") == env

    def test_invalid_env_warns_and_falls_through(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        bundled = _make_dist(tmp_path, "bundled")
        result = resolve_frontend(None, str(tmp_path / "ghost-env"), bundled=bundled)
        assert result == bundled
        assert "ALC_UI_DIST" in capsys.readouterr().err

    def test_bundled_used_when_no_flag_or_env(self, tmp_path: Path) -> None:
        bundled = _make_dist(tmp_path, "bundled")
        assert resolve_frontend(None, None, bundled=bundled) == bundled

    def test_none_when_nothing_available(self, tmp_path: Path) -> None:
        assert resolve_frontend(None, None, bundled=tmp_path / "bundled") is None

    def test_no_ui_forces_none(self, tmp_path: Path) -> None:
        flag = _make_dist(tmp_path, "flag")
        bundled = _make_dist(tmp_path, "bundled")
        assert resolve_frontend(str(flag), None, no_ui=True, bundled=bundled) is None


# ---------------------------------------------------------------------------
# cmd_ui: exit codes and startup message (uvicorn.run stubbed out)
# ---------------------------------------------------------------------------


def _ui_args(**overrides) -> argparse.Namespace:
    base = {"host": "127.0.0.1", "port": 8642, "ui_dist": None, "no_ui": False}
    base.update(overrides)
    return argparse.Namespace(**base)


@pytest.fixture
def stub_uvicorn(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict:
    """Prevent cmd_ui from actually blocking on a real server.

    Registry and cwd isolated for the same reason as test_ui_lan's fixture:
    cmd_ui writes the project above the cwd into the shared registry, and a
    pytest run inside a worktree was registering that worktree as a ghost
    project.
    """
    calls: dict = {}
    import uvicorn

    def _fake_run(app, host, port):  # noqa: ANN001
        calls["host"] = host
        calls["port"] = port

    monkeypatch.setattr(uvicorn, "run", _fake_run)
    registry = tmp_path / "projects.json"
    monkeypatch.setattr("alc.ui.registry.default_registry_path", lambda: registry)
    monkeypatch.setattr("alc.cli.default_registry_path", lambda: registry, raising=False)
    monkeypatch.chdir(tmp_path)
    return calls


class TestCmdUi:
    def test_invalid_ui_dist_exits_1(
        self, tmp_path: Path, stub_uvicorn: dict, capsys: pytest.CaptureFixture
    ) -> None:
        code = cmd_ui(_ui_args(ui_dist=str(tmp_path / "ghost")))
        assert code == 1
        assert "index.html" in capsys.readouterr().err
        assert stub_uvicorn == {}  # never reached uvicorn.run

    def test_no_ui_serves_api_only(
        self, stub_uvicorn: dict, capsys: pytest.CaptureFixture
    ) -> None:
        code = cmd_ui(_ui_args(no_ui=True))
        assert code == 0
        assert "(API only)" in capsys.readouterr().out
        assert stub_uvicorn["port"] == 8642

    def test_valid_ui_dist_serves_frontend(
        self, tmp_path: Path, stub_uvicorn: dict, capsys: pytest.CaptureFixture
    ) -> None:
        dist = _make_dist(tmp_path)
        code = cmd_ui(_ui_args(ui_dist=str(dist)))
        assert code == 0
        assert f"frontend: {dist}" in capsys.readouterr().out

    def test_no_frontend_prints_hint(
        self,
        tmp_path: Path,
        stub_uvicorn: dict,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        monkeypatch.delenv("ALC_UI_DIST", raising=False)
        monkeypatch.setattr("alc.ui.frontend.BUNDLED_DIR", tmp_path / "no-bundle")
        code = cmd_ui(_ui_args())
        assert code == 0
        captured = capsys.readouterr()
        assert "(API only)" in captured.out
        assert "npm run build:alc" in captured.err
