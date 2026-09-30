"""资源管理器：单次初始化、并发安全、可重复关闭。"""

from __future__ import annotations

from typing import Any

from app.resources.base import Resource


class ResourceManager:
    def __init__(self) -> None:
        raise NotImplementedError

    def register(self, resource: Resource) -> None:
        raise NotImplementedError

    async def startup_all(self) -> None:
        raise NotImplementedError

    async def shutdown_all(self) -> None:
        raise NotImplementedError

    def get(self, name: str) -> Any:
        raise NotImplementedError

    def require(self, name: str) -> Any:
        raise NotImplementedError
