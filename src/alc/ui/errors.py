# errors.py — One error type for the UI backend, mapped to an HTTP response.
from __future__ import annotations

from typing import Any


class ApiError(Exception):
    """A backend error carrying an HTTP status and an optional structured detail.

    Raised by the service/collection/command layers; a single FastAPI exception
    handler (registered in server.create_app) turns it into a JSON response so
    the route handlers stay thin.
    """

    def __init__(self, message: str, status: int = 422, detail: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.detail = detail
