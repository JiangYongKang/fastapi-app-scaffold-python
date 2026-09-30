"""路由登记：按模块登记、统一前缀、启动期冲突检测。"""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import APIRouter


class RouteConflictError(Exception):
    """路由重复或前缀冲突。"""


class ModuleRegistration:
    """一次模块登记记录。"""

    def __init__(self, module_name: str, prefix: str, router: APIRouter) -> None:
        raise NotImplementedError


class RouteRegistry:
    def __init__(self) -> None:
        raise NotImplementedError

    def register_module(self, module_name: str, prefix: str, router: APIRouter) -> None:
        raise NotImplementedError

    def registrations(self) -> Sequence[ModuleRegistration]:
        raise NotImplementedError

    def mount_all(self, app: object) -> None:
        raise NotImplementedError
