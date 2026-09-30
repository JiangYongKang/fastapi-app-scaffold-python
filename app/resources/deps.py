"""FastAPI 依赖工厂：把资源状态检查接入请求处理。"""

from __future__ import annotations

from typing import Any


def resource_dependency(name: str) -> Any:
    """返回一个 FastAPI 依赖，按资源状态放行或拒绝请求。"""
    raise NotImplementedError
