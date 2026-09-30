"""Shared domain error types mapped to the unified error envelope."""

from __future__ import annotations


class AppError(Exception):
    """Base class for expected application errors."""

    status_code: int = 400
    code: str = "app_error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ResourceNotReadyError(AppError):
    """A request reached a resource before startup completed."""

    status_code = 503
    code = "resource_not_ready"


class ResourceReleasedError(AppError):
    """A request reached a resource after shutdown released it."""

    status_code = 503
    code = "resource_released"


class ResourceError(AppError):
    """Generic resource failure (distinct from readiness errors)."""

    status_code = 500
    code = "resource_error"


class RouteConflictError(Exception):
    """Raised at startup when module routes conflict."""
