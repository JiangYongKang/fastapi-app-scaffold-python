"""路由登记与冲突检测包。"""

from __future__ import annotations

from app.routing.registry import (
    ModuleRegistration,
    RouteConflictError,
    RouteRegistry,
)

__all__ = [
    "ModuleRegistration",
    "RouteConflictError",
    "RouteRegistry",
]
