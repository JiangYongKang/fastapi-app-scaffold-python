"""资源管理器：登记、单次初始化、并发安全、幂等关闭。

关键保证：

* **只初始化一次**：每个资源有独立的 ``asyncio.Lock``，
  即使多个协程同时触发启动，真正的 ``startup()`` 也只会执行一次；
* **就绪前/释放后拒绝请求**：:meth:`get` 按资源状态抛出
  :class:`ResourceNotReadyError` 或 :class:`ResourceReleasedError`，
  调用方可以区分"还没好"和"已经没了"；
* **关闭可重复执行**：:meth:`shutdown_all` 多次调用不报错、不重复释放。
"""

from __future__ import annotations

import asyncio

from app.resources.base import Resource, ResourceState
from app.resources.errors import (
    ResourceAlreadyRegisteredError,
    ResourceNotFoundError,
    ResourceNotReadyError,
    ResourceReleasedError,
)


class ResourceManager:
    def __init__(self) -> None:
        self._resources: dict[str, Resource] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._startup_lock = asyncio.Lock()
        self._shutdown_lock = asyncio.Lock()
        self._started = False
        self._stopped = False

    # ------------------------------------------------------------------ 登记
    def register(self, resource: Resource) -> None:
        """登记一个资源。必须在应用启动前完成；重名立即报错。"""
        name = resource.name
        if not name:
            raise ValueError("资源必须声明非空的 name")
        if name in self._resources:
            raise ResourceAlreadyRegisteredError(
                f"资源 {name!r} 已被 "
                f"{type(self._resources[name]).__name__} 登记，不能重复登记"
            )
        self._resources[name] = resource
        self._locks[name] = asyncio.Lock()

    def __contains__(self, name: object) -> bool:
        return name in self._resources

    def names(self) -> tuple[str, ...]:
        return tuple(self._resources)

    def state_of(self, name: str) -> ResourceState:
        resource = self._resources.get(name)
        if resource is None:
            raise ResourceNotFoundError(f"资源 {name!r} 未登记")
        return resource.state

    # ------------------------------------------------------------------ 启动
    async def _start_one(self, resource: Resource) -> None:
        """在单资源锁内完成启动，保证并发下 startup 只执行一次。"""
        lock = self._locks[resource.name]
        async with lock:
            if resource.state is ResourceState.READY:
                return  # 已被另一个协程初始化
            if resource.state is ResourceState.RELEASED:
                raise ResourceReleasedError(
                    f"资源 {resource.name!r} 已经释放，不能再次初始化"
                )
            # CREATED（STARTING 不可能在持锁状态下被观察到）
            resource.state = ResourceState.STARTING
            try:
                await resource.startup()
            except BaseException:
                resource.state = ResourceState.CREATED  # 允许后续重试
                raise
            resource.state = ResourceState.READY

    async def startup_all(self) -> None:
        """按登记顺序启动全部资源；重复调用直接返回，不会二次初始化。"""
        async with self._startup_lock:
            if self._started:
                return
            for resource in tuple(self._resources.values()):
                await self._start_one(resource)
            self._started = True

    # ------------------------------------------------------------------ 关闭
    async def shutdown_all(self) -> None:
        """按登记逆序释放资源；重复调用安全（幂等）。"""
        async with self._shutdown_lock:
            if self._stopped:
                return
            self._stopped = True
            for resource in reversed(tuple(self._resources.values())):
                if resource.state is ResourceState.READY:
                    resource.state = ResourceState.STOPPING
                    try:
                        await resource.shutdown()
                    finally:
                        resource.state = ResourceState.RELEASED
                else:
                    # 未就绪/启动失败的资源没有可释放的实体，直接标记
                    resource.state = ResourceState.RELEASED

    # ------------------------------------------------------------------ 取用
    def get(self, name: str) -> Resource:
        """按状态获取资源。

        * 未登记 → :class:`ResourceNotFoundError`
        * 未就绪（CREATED/STARTING）→ :class:`ResourceNotReadyError`
        * 正在关闭/已释放（STOPPING/RELEASED）→ :class:`ResourceReleasedError`
        """
        resource = self._resources.get(name)
        if resource is None:
            raise ResourceNotFoundError(f"资源 {name!r} 未登记")

        if resource.state is ResourceState.READY:
            return resource
        if resource.state in (ResourceState.STOPPING, ResourceState.RELEASED):
            raise ResourceReleasedError(
                f"资源 {name!r} 已释放或正在关闭"
                f"（state={resource.state.value}），请求被拒绝"
            )
        raise ResourceNotReadyError(
            f"资源 {name!r} 尚未就绪（state={resource.state.value}），"
            f"请在应用启动完成后再试"
        )

    def snapshot(self) -> dict[str, str]:
        """返回所有资源的当前状态（用于健康检查/日志）。"""
        return {name: r.state.value for name, r in self._resources.items()}
