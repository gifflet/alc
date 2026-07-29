#!/usr/bin/env bash
# release.sh — Build the web IDE into the package and (re)install the global `alc`.
#
# WHY THIS EXISTS: `alc ui` serves a pre-built frontend bundle from
# src/alc/ui/static/ — a build artifact (gitignored) produced by the frontend's
# `npm run build:alc`, NOT by the Python install. So a version bump +
# `uv tool install` alone ships a STALE UI. Worse, because static/ is gitignored,
# uv's build cache reuses a prior wheel and silently packages the old bundle.
#
# This script does the whole chain, in the CI-canonical order:
#   1. build the frontend into the package (mirrors release.yml's build:alc step);
#   2. reinstall the global tool WITHOUT uv's build cache and WITH the [ui] extra;
#   3. guard: assert the freshly built bundle is the one that got installed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VERSION=$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
echo "▶ releasing alc $VERSION → global install"

# 1. Build the frontend into src/alc/ui/static/. npm ci only when deps are
#    missing (a fresh checkout) so repeated local runs stay fast.
echo "▶ building the web IDE (ui → src/alc/ui/static/)"
[ -d ui/node_modules ] || ( cd ui && npm ci )
( cd ui && npm run build:alc )

# 2. Reinstall the global tool. --no-cache is LOAD-BEARING: static/ is gitignored,
#    so uv's build cache would otherwise reuse a stale wheel. [ui] keeps the web
#    IDE's runtime deps (fastapi/uvicorn/watchfiles).
echo "▶ installing the global alc-runtime[ui] (no build cache)"
uv tool install --force --reinstall --no-cache ".[ui]"

# 3. Guard: the installed bundle must be the one we just built — the exact
#    stale-bundle failure this script exists to prevent. NOTE the tool dir is named
#    after the DISTRIBUTION (`alc-runtime`), not the `alc` command it installs.
echo "▶ verifying the installed bundle matches the fresh build"
fresh_index="$(basename "$(ls src/alc/ui/static/assets/index-*.js | head -1)")"
installed_assets="$(find "$(uv tool dir)/alc-runtime" -type d -path "*/alc/ui/static/assets" 2>/dev/null | head -1)"
if [ -z "$installed_assets" ] || [ ! -f "$installed_assets/$fresh_index" ]; then
  echo "✗ installed UI is stale: '$fresh_index' not found in the installed tool" >&2
  exit 1
fi

echo "✓ alc $VERSION installed with a fresh web IDE — restart 'alc ui' to pick it up"
