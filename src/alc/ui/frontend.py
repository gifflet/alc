# frontend.py — Resolve which frontend directory `alc ui` serves.
#
# The UI is served BY DEFAULT (opt-out via --no-ui). The resolution order lets
# an explicit path win, then the environment, then a bundled build shipped
# inside the package, and finally falls back to API-only.
from __future__ import annotations

import sys
from pathlib import Path

# The frontend build bundled inside the package. It is a build artifact
# (gitignored) produced by the alc-ui frontend's `npm run build:alc`: absent in
# a plain source checkout, present in a packaged/installed build.
BUNDLED_DIR = Path(__file__).parent / "static"


class FrontendError(Exception):
    """An explicit --ui-dist path is invalid; the CLI reports it and exits 1."""


def has_index(path: Path) -> bool:
    """True when *path* is a directory containing an index.html."""
    return path.is_dir() and (path / "index.html").is_file()


def resolve_frontend(
    ui_dist: str | None,
    env_dist: str | None,
    *,
    no_ui: bool = False,
    bundled: Path | None = None,
) -> Path | None:
    """Resolve the frontend directory to serve, or None for API-only.

    Order (unless ``no_ui`` is set, which forces None):
      1. explicit ``ui_dist`` — must contain index.html, else FrontendError
         (no silent fallback for an explicit path);
      2. ``env_dist`` (ALC_UI_DIST) — used when valid, else a warning + skip;
      3. the ``bundled`` static dir — used when it contains index.html;
      4. None (API-only).
    """
    if bundled is None:
        bundled = BUNDLED_DIR

    if no_ui:
        return None

    if ui_dist:
        path = Path(ui_dist).expanduser()
        if not has_index(path):
            raise FrontendError(
                f"--ui-dist '{ui_dist}' has no index.html "
                f"(expected {path / 'index.html'})"
            )
        return path

    if env_dist:
        path = Path(env_dist).expanduser()
        if has_index(path):
            return path
        print(
            f"[WARN] ALC_UI_DIST '{env_dist}' has no index.html; ignoring it.",
            file=sys.stderr,
        )

    if has_index(bundled):
        return bundled

    return None
