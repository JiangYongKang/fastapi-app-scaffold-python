"""FastAPI 依赖工厂：把资源状态检查接入请求处理。

用法::

    def get_items(r: Resource = Depends(resource_dependency("database"))):
        ...

资源未就绪或已释放时，依赖抛出资源域异常，由全局异常处理器统一转换为
相同结构的 503 响应，且两种原因的 ``code`` 不同、可区分。
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Request

from app.resources.base import Resource


def _get_manager(request: Request):
    """从应用状态中取出资源管理器（由 application 装配时注入）。"""
    return request.app.state.resources


def resource_dependency(name: str) -> Callable[..., Resource]:
    """生成一个依赖：资源 READY 时返回资源实例，否则抛出资源域异常。"""

    def _depends(request: Request) -> Resource:
        manager = _get_manager(request)
        return manager.get(name)

    _depends.__name__ = f"require_resource_{name}"
    return _depends
