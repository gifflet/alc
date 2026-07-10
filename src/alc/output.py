# output.py — the uniform machine-readable output for ALC's list/info commands.
#
# Human-readable is the DEFAULT (terminal UX); a `--json` flag emits the SAME data
# as JSON for scripting — one shared helper so every listing is consistent across
# commands (the convention: default human, opt-in `--json`, like `gh` / `kubectl`).
from __future__ import annotations

import json
from typing import Any


def emit_json(data: Any) -> None:
    """Print *data* (any JSON-serializable value) as pretty JSON to stdout."""
    print(json.dumps(data, indent=2, default=str))
