# server.py — The `alc ui` FastAPI app factory.
#
# create_app wires the project registry, the in-memory event bus, the exec
# RunManager and the file watcher, mounts the API routers and (optionally) the
# built SPA. It is import-safe only WITH the `ui` extra installed (fastapi); the
# CLI imports it lazily so `alc ui` without the extra fails with a clear message.
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from alc.ui import (
    routes_branches,
    routes_checks,
    routes_config,
    routes_exec,
    routes_fleet,
    routes_inbox,
    routes_metrics,
    routes_projects,
    routes_queue,
    routes_run_configs,
    routes_schedule,
    routes_signals,
    routes_team,
    routes_variants,
    ws,
)
from alc.ui.auth import require_token
from alc.ui.bus import EventBus
from alc.ui.errors import ApiError
from alc.ui.execs import RunManager
from alc.ui.registry import ProjectRegistry
from alc.ui.watch import Watcher


def _register_spa(app: FastAPI, ui_dist: Path) -> None:
    """Serve the built SPA via a catch-all GET, never shadowing /api or /ws.

    A plain HTTP GET route only matches ``http`` scopes, so the WebSocket route
    (a ``websocket`` scope) always wins for /ws — even if the server downgrades
    a WS upgrade to HTTP. /api paths are explicitly excluded so an unknown API
    route stays a JSON 404 rather than being answered with index.html.
    """
    ui_dist = ui_dist.resolve()
    index = ui_dist / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        if full_path == "ws" or full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = (ui_dist / full_path).resolve()
        if candidate.is_file() and candidate.is_relative_to(ui_dist):
            return FileResponse(candidate)
        return FileResponse(index)


def create_app(
    registry_path: Path,
    *,
    ui_dist: Path | None = None,
    enable_watch: bool = True,
    token: str | None = None,
) -> FastAPI:
    """Build the `alc ui` FastAPI application.

    Args:
        registry_path: Path to the projects.json registry (injectable for tests).
        ui_dist: If given and it exists, the built frontend is served as an SPA.
        enable_watch: Start the .alc/ file watcher in the lifespan (off in tests
            that drive the EventBus directly).
        token: When set, every /api request must carry
            ``Authorization: Bearer <token>`` and the WebSocket must open with an
            auth frame. Unset (the default) leaves the server exactly as it was:
            local and unauthenticated.
    """
    registry = ProjectRegistry(registry_path)
    bus = EventBus()
    run_manager = RunManager(bus)
    watcher = Watcher(registry, bus)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        bus.bind_loop(asyncio.get_running_loop())
        if enable_watch:
            watcher.start()
        try:
            yield
        finally:
            watcher.stop()

    app = FastAPI(title="alc ui", lifespan=lifespan)
    app.state.registry = registry
    app.state.token = token
    app.state.bus = bus
    app.state.run_manager = run_manager
    app.state.watcher = watcher

    @app.middleware("http")
    async def _no_store_api(request: Request, call_next):
        # API responses are live project state — the control room must reflect
        # the actual project, never a browser-cached snapshot (a stale audit or
        # roster would misrepresent the truth). Static SPA assets (hashed,
        # immutable) are untouched and keep their default caching.
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ApiError)
    async def _handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        body: dict = {"detail": exc.message}
        if exc.detail is not None:
            body["violations"] = exc.detail
        return JSONResponse(status_code=exc.status, content=body)

    # Specific/literal routers first; the generic /{collection} catch-all in
    # routes_config is included LAST so it never shadows queue/runs/exec routes.
    api_guard = [Depends(require_token)]
    app.include_router(routes_projects.router, dependencies=api_guard)
    app.include_router(routes_queue.router, dependencies=api_guard)
    app.include_router(routes_run_configs.router, dependencies=api_guard)
    app.include_router(routes_run_configs.project_router, dependencies=api_guard)
    app.include_router(routes_exec.project_router, dependencies=api_guard)
    app.include_router(routes_exec.router, dependencies=api_guard)
    app.include_router(routes_fleet.router, dependencies=api_guard)
    app.include_router(routes_inbox.router, dependencies=api_guard)
    app.include_router(routes_team.router, dependencies=api_guard)
    app.include_router(routes_branches.router, dependencies=api_guard)
    app.include_router(routes_variants.router, dependencies=api_guard)
    app.include_router(routes_signals.router, dependencies=api_guard)
    app.include_router(routes_metrics.router, dependencies=api_guard)
    app.include_router(routes_checks.router, dependencies=api_guard)
    app.include_router(routes_schedule.router, dependencies=api_guard)
    app.include_router(routes_config.router, dependencies=api_guard)
    # The WebSocket route is registered BEFORE the SPA catch-all so /ws always
    # resolves to the WS handler.
    ws.register(app)

    if ui_dist is not None and Path(ui_dist).is_dir():
        _register_spa(app, Path(ui_dist))

    return app
