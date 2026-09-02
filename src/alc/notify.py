# notify.py — Never-raise push notifications for unattended operation.
#
# A notify target is either a command (argv list, no shell — the payload is
# handed to it on stdin) or a webhook URL (a str — the payload is POSTed as the
# body). No per-service adapters: the operator already knows how to fan a command
# or URL out to Slack, email, or a pager. Absent target (None/empty) = no-op,
# byte-identical to today.
#
# Same never-raise contract as events.py/commit.py: a delivery failure (bad
# command, unreachable URL, timeout) is swallowed and warned to stderr — it must
# NEVER fail the work it is reporting on.
#
# stdlib only, no new dependency.
from __future__ import annotations

import json
import subprocess
import sys
import urllib.request

# A command (argv list) or a webhook URL (str); None/empty = off.
NotifyTarget = list[str] | str | None

_TIMEOUT_S = 10  # delivery must never hang a run waiting on a slow/dead endpoint


def fire(target: NotifyTarget, event: str, **payload: object) -> None:
    """Best-effort delivery of *event* to *target*.

    No-op when *target* is None or empty. The body is
    ``{"event": event, **payload}`` as JSON, sent on stdin to a command (a list)
    or as the POST body to a webhook URL (a str). Never raises: any failure —
    a missing binary, a non-zero exit, an unreachable URL, a timeout — is caught
    and printed to stderr, exactly like the work it is reporting on would be if
    this function did not exist.
    """
    if not target:
        return
    body = json.dumps({"event": event, **payload}, default=str)
    try:
        if isinstance(target, str):
            _post_webhook(target, body)
        else:
            _run_command(target, body)
    except Exception as exc:
        print(f"[notify] {event} -> {target!r} failed: {exc}", file=sys.stderr)


def _run_command(argv: list[str], body: str) -> None:
    """Run *argv* (no shell) with *body* on stdin; raise on a non-zero exit."""
    result = subprocess.run(
        argv, input=body, capture_output=True, text=True, timeout=_TIMEOUT_S
    )
    if result.returncode != 0:
        raise RuntimeError(f"exited {result.returncode}: {result.stderr.strip()}")


def _post_webhook(url: str, body: str) -> None:
    """POST *body* as JSON to *url*; raise on any transport/HTTP error."""
    request = urllib.request.Request(
        url,
        data=body.encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
        response.read()
