"""Domain errors and their mapping to HTTP responses.

Services raise these; the API layer turns them into a uniform JSON error body:
``{"error": {"code": "...", "message": "...", "details": {...}}}``.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError


class DomainError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, details: dict[str, Any] | None = None, headers: dict[str, str] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.headers = headers or {}


class ValidationFailed(DomainError):
    status_code = 422
    code = "validation_failed"


class NotFound(DomainError):
    status_code = 404
    code = "not_found"


class Unauthorized(DomainError):
    status_code = 401
    code = "unauthorized"


class Forbidden(DomainError):
    status_code = 403
    code = "forbidden"


class Conflict(DomainError):
    status_code = 409
    code = "conflict"


class TooManyRequests(DomainError):
    """Too many failed attempts; the ``Retry-After`` header tells when to try again."""

    status_code = 429
    code = "too_many_requests"


class Locked(DomainError):
    """The object is frozen by its lifecycle state (e.g. in review or released)."""

    status_code = 423
    code = "locked"


def _body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


# PostgreSQL states of a concurrent change: unique/foreign key violation, serialization failure, deadlock, lock timeout
CONFLICTING_STATES = {"23505", "23503", "40001", "40P01", "55P03"}
CONFLICT_MESSAGE = "The data was changed at the same time by someone else — reload and try again"


def sqlstate(exc: DBAPIError) -> str | None:
    return getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)


def install_error_handlers(app: FastAPI) -> None:
    from almlight.core.i18n import request_locale, tr

    @app.exception_handler(DomainError)
    async def _domain(request: Request, exc: DomainError) -> JSONResponse:
        message = tr(exc.message, request_locale(request)) or exc.message
        return JSONResponse(status_code=exc.status_code, content=_body(exc.code, message, exc.details),
                            headers=exc.headers or None)

    @app.exception_handler(DBAPIError)
    async def _database(request: Request, exc: DBAPIError) -> JSONResponse:
        if sqlstate(exc) not in CONFLICTING_STATES:
            raise exc  # a real fault: the handler below answers and the server logs it
        message = tr(CONFLICT_MESSAGE, request_locale(request)) or CONFLICT_MESSAGE
        return JSONResponse(status_code=409, content=_body("conflict", message))

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        """Unexpected faults answer in the usual JSON form (the server still logs the traceback)."""
        message = tr("Internal server error", request_locale(request)) or "Internal server error"
        return JSONResponse(status_code=500, content=_body("internal_error", message),
                            headers={"Cache-Control": "no-store"})

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422, content=_body("validation_failed",
                                           tr("Request validation failed", request_locale(request)) or "",
                                           {"errors": errors})
        )
