"""Domain errors and their mapping to HTTP responses.

Services raise these; the API layer turns them into a uniform JSON error body:
``{"error": {"code": "...", "message": "...", "details": {...}}}``.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class DomainError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


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


class Locked(DomainError):
    """The object is frozen by its lifecycle state (e.g. in review or released)."""

    status_code = 423
    code = "locked"


def _body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def install_error_handlers(app: FastAPI) -> None:
    from almlight.core.i18n import request_locale, tr

    @app.exception_handler(DomainError)
    async def _domain(request: Request, exc: DomainError) -> JSONResponse:
        message = tr(exc.message, request_locale(request)) or exc.message
        return JSONResponse(status_code=exc.status_code, content=_body(exc.code, message, exc.details))

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
