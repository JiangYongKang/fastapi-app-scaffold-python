"""路由登记：按模块登记、统一前缀、启动期冲突检测。

设计要点：

* 每个业务模块以 ``(模块名, 前缀, APIRouter)`` 三元组登记；
* 统一挂载在配置的 ``api.prefix`` 下，最终全路径为
  ``api.prefix + 模块前缀 + 路由路径``；
* **冲突在启动阶段直接报错**（不会悄悄覆盖）：
  - 模块名重复；
  - 模块前缀重复；
  - 任意两个模块出现"HTTP 方法 + 全路径"完全相同的路由。

路径比较做末尾斜杠归一化（``/x`` 与 ``/x/`` 视为冲突），
因为 FastAPI 默认就把它们当作同一路由匹配。
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, FastAPI

HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")


class RouteConflictError(Exception):
    """路由重复或前缀冲突（启动期失败）。"""


@dataclass(frozen=True)
class ModuleRegistration:
    module_name: str
    prefix: str
    router: APIRouter

    @property
    def full_prefix(self) -> str:
        """统一加上 API 前缀后的完整模块前缀（挂载前由 app 注入）。"""
        return self.prefix


def _normalize_path(path: str) -> str:
    """归一化路径：去末尾斜杠（根路径除外）。"""
    if len(path) > 1 and path.endswith("/"):
        return path.rstrip("/")
    return path


def _join_prefix(api_prefix: str, module_prefix: str) -> str:
    """拼接统一 API 前缀与模块前缀，避免根前缀产生双斜杠。

    例如 ``/api`` + ``/`` -> ``/api``；``/api`` + ``/x`` -> ``/api/x``。
    """
    base = api_prefix.rstrip("/")
    module_prefix = module_prefix.strip()
    if not module_prefix.startswith("/"):
        raise RouteConflictError(
            f"模块前缀 {module_prefix!r} 必须以 '/' 开头"
        )
    if module_prefix == "/":
        return base
    return base + module_prefix


def _route_endpoints(
    router: APIRouter, full_prefix: str
) -> list[tuple[str, str]]:
    """提取路由的 (方法, 全路径) 列表（保留重复，用于检测模块内冲突）。"""
    endpoints: list[tuple[str, str]] = []
    for route in router.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path is None or not methods:
            continue
        full_path = _normalize_path(full_prefix + path)
        for method in methods:
            upper = method.upper()
            if upper in HTTP_METHODS:
                endpoints.append((upper, full_path))
    return endpoints


class RouteRegistry:
    def __init__(self, api_prefix: str = "/api") -> None:
        self._api_prefix = api_prefix
        self._registrations: list[ModuleRegistration] = []
        self._names: set[str] = set()
        self._prefixes: set[str] = set()
        self._endpoints: dict[tuple[str, str], str] = {}

    def register_module(
        self, module_name: str, prefix: str, router: APIRouter
    ) -> None:
        """登记一个业务模块；任何冲突立即抛 :class:`RouteConflictError`。"""
        if not module_name:
            raise RouteConflictError("模块名不能为空")
        if module_name in self._names:
            raise RouteConflictError(
                f"模块名 {module_name!r} 重复登记"
            )

        prefix = prefix.strip()
        if not prefix.startswith("/"):
            raise RouteConflictError(
                f"模块 {module_name!r} 的前缀 {prefix!r} 必须以 '/' 开头"
            )
        normalized_prefix = _normalize_path(prefix)
        if normalized_prefix in self._prefixes:
            owner = next(
                r.module_name
                for r in self._registrations
                if _normalize_path(r.prefix) == normalized_prefix
            )
            raise RouteConflictError(
                f"模块 {module_name!r} 的前缀 {prefix!r} 与已登记模块 "
                f"{owner!r} 冲突：同一前缀不允许由多个模块声明"
            )

        full_prefix = _join_prefix(self._api_prefix, prefix)
        for method, full_path in _route_endpoints(router, full_prefix):
            existing = self._endpoints.get((method, full_path))
            if existing is not None:
                raise RouteConflictError(
                    f"路由冲突：{method} {full_path} 同时被模块 "
                    f"{existing!r} 与 {module_name!r} 登记，"
                    f"后登记的路由不允许覆盖先登记的"
                )
            self._endpoints[(method, full_path)] = module_name

        self._registrations.append(
            ModuleRegistration(module_name, prefix, router)
        )
        self._names.add(module_name)
        self._prefixes.add(normalized_prefix)

    def registrations(self) -> tuple[ModuleRegistration, ...]:
        return tuple(self._registrations)

    def mount_all(self, app: FastAPI) -> None:
        """把全部模块统一挂载到 api.prefix 下。"""
        for reg in self._registrations:
            app.include_router(
                reg.router,
                prefix=_join_prefix(self._api_prefix, reg.prefix),
                tags=[reg.module_name],
            )
