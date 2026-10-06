"""Application-level exceptions mapped to HTTP responses by ``main.py``.

Routes raise these instead of ``HTTPException`` so every error flows through
one custom handler that emits the shared :class:`~app.schemas.common.ErrorResponse`
envelope (including the request id for log correlation).
"""

from __future__ import annotations

from typing import Any


class APIError(Exception):
    """Base class for all API-facing errors."""

    status_code: int = 500
    code: str = "internal_error"
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        status_code: int | None = None,
        detail: Any = None,
    ) -> None:
        self.message = message or self.message
        if status_code is not None:
            self.status_code = status_code
        self.detail = detail
        super().__init__(self.message)

    def to_payload(self) -> dict[str, Any]:
        """Error envelope body (``{"error": {...}}``)."""

        payload: dict[str, Any] = {
            "error": {
                "code": self.status_code,
                "message": self.message,
                "detail": self.detail,
            }
        }
        return payload


class NotFoundError(APIError):
    """Requested resource does not exist (404)."""

    status_code = 404
    code = "not_found"
    message = "Resource not found."

    def __init__(self, resource: str = "Resource", identifier: Any = None) -> None:
        super().__init__(
            f"{resource} not found."
            if identifier is None
            else f"{resource} '{identifier}' not found.",
            detail={"resource": resource, "id": str(identifier) if identifier is not None else None},
        )


class BadRequestError(APIError):
    """Malformed or conflicting request (400)."""

    status_code = 400
    code = "bad_request"
    message = "Invalid request."


class ConflictError(APIError):
    """Request conflicts with current state (409)."""

    status_code = 409
    code = "conflict"
    message = "Request conflicts with the current state."


class ServiceUnavailableError(APIError):
    """A required dependency is unavailable (503)."""

    status_code = 503
    code = "service_unavailable"
    message = "Service temporarily unavailable."


class RateLimitedError(APIError):
    """Too many requests (429)."""

    status_code = 429
    code = "rate_limited"
    message = "Too many requests - slow down."
