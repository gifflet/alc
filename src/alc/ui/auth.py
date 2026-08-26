# auth.py — Optional bearer-token gate for the UI API and WebSocket.
#
# `alc ui` is a single-user local tool: with no token configured it stays exactly
# what it has always been — an unauthenticated server on 127.0.0.1. A token is
# what makes it safe to reach over a tunnel from a phone, which is the whole
# point of the mobile surface (`alc serve --webhook --token` set this precedent).
#
# One branch, not a second code path: when no token is configured the dependency
# allows unconditionally, so the default behaviour cannot drift.
from __future__ import annotations

import hmac

from fastapi import Request, WebSocket

from alc.ui.errors import ApiError

# Close code for a WebSocket that never presented a valid token. 4000-4999 is
# the application-private range; 4401 mirrors HTTP 401 for readability.
WS_UNAUTHORIZED = 4401


def configured_token(app_state) -> str | None:
    """The token this server requires, or None when auth is off."""
    return getattr(app_state, "token", None)


def token_matches(expected: str | None, presented: str | None) -> bool:
    """Constant-time comparison; True when no token is configured.

    ``hmac.compare_digest`` (never ``==``) so a caller cannot learn the token
    one character at a time from response timing.
    """
    if not expected:
        return True
    if not presented:
        return False
    return hmac.compare_digest(expected, presented)


def bearer_from_header(header: str | None) -> str | None:
    """Extract the credential from an ``Authorization: Bearer <token>`` header."""
    if not header:
        return None
    scheme, _, credential = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return credential.strip() or None


def require_token(request: Request) -> None:
    """FastAPI dependency: 401 unless the request carries the configured token.

    A no-op when the server was started without one.
    """
    expected = configured_token(request.app.state)
    if not expected:
        return
    presented = bearer_from_header(request.headers.get("authorization"))
    if not token_matches(expected, presented):
        raise ApiError("missing or invalid token", status=401)


def ws_token_accepted(websocket: WebSocket, message: object) -> bool:
    """Whether an opening WebSocket frame satisfies the token requirement.

    Browsers cannot set headers on a WebSocket handshake, so the client sends
    ``{"type": "auth", "token": …}`` as its FIRST frame. A query-string token was
    rejected on purpose: it would be written to every proxy and server log on the
    path.
    """
    expected = configured_token(websocket.app.state)
    if not expected:
        return True
    if not isinstance(message, dict) or message.get("type") != "auth":
        return False
    presented = message.get("token")
    return isinstance(presented, str) and token_matches(expected, presented)
