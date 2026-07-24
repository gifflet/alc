# test_no_store.py — API responses must never be browser-cached, so the live
# control room always reflects the actual project state (not a stale snapshot).
from __future__ import annotations


def test_api_responses_carry_no_store(client) -> None:
    res = client.get("/api/projects")
    assert res.status_code == 200
    assert res.headers.get("cache-control") == "no-store"


def test_non_api_paths_are_not_forced_no_store(client) -> None:
    # The middleware only touches /api/* — a non-API path (here a 404, since the
    # SPA bundle is not mounted in tests) must not be stamped no-store, so hashed
    # static assets keep their default caching in production.
    res = client.get("/not-an-api-path")
    assert res.headers.get("cache-control") != "no-store"
