"""资源生命周期管理包。"""

from __future__ import annotations

from app.resources.base import Resource, ResourceState
from app.resources.deps import resource_dependency
from app.resources.errors import (
    ResourceAlreadyRegisteredError,
    ResourceError,
    ResourceNotFoundError,
    ResourceNotReadyError,
    ResourceReleasedError,
)
from app.resources.manager import ResourceManager

__all__ = [
    "Resource",
    "ResourceAlreadyRegisteredError",
    "ResourceError",
    "ResourceManager",
    "ResourceNotFoundError",
    "ResourceNotReadyError",
    "ResourceReleasedError",
    "ResourceState",
    "resource_dependency",
]
