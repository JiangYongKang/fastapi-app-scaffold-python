"""Unified error response envelope.

Every error returned by the API -- expected application errors, request
validation errors, routing conflicts surfaced at runtime, and unexpected
exceptions -- uses the same body::

    {"error": {"code": "...", "message": "...", "details": {...}}}

Unexpected exceptions are never leaked verbatim: in non-debug mode clients
only see a generic ``internal_error``; the real exception stays in the
server log.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import AppError, RouteConflictError

logger = logging.getLogger("app.errors")


def error_body(code: str, message: str, details: dict | None = None) -> dict:
    body: dict = {"code": code, "message": message}
    if details:
        body["details"] = details
    return {"error": body}


def register_exception_handlers(app: FastAPI, *, debug: bool = False) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        fields = [
            {
                "field": ".".join(str(p) for p in err.get("loc", []) if p != "body"),
                "message": err.get("msg", ""),
                "type": err.get("type", ""),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=error_body(
                "validation_error",
                "request validation failed",
                {"fields": fields},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            code, message = "not_found", "resource not found"
        elif exc.status_code == 405:
            code, message = "method_not_allowed", "method not allowed"
        else:
            code, message = "http_error", str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(code, message),
        )

    @app.exception_handler(RouteConflictError)
    async def _handle_route_conflict(
        _: Request, exc: RouteConflictError
    ) -> JSONResponse:
        # Route conflicts normally abort startup; if one is ever raised while
        # serving a request it must still arrive in the standard envelope.
        return JSONResponse(
            status_code=500,
            content=error_body("route_conflict", str(exc)),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled exception while serving %s %s",
            request.method,
            request.url.path,
        )
        details: dict = {}
        if debug:
            details = {"exception": type(exc).__name__}
        return JSONResponse(
            status_code=500,
            content=error_body(
                "internal_error",
                "an internal error occurred",
                details or None,
            ),
        )
