"""资源生命周期测试。

覆盖：
* 并发启动只初始化一次；
* 未就绪/已释放两种拒绝原因可区分；
* 关闭幂等（重复执行不报错、不重复释放）；
* 启动失败后回到 CREATED 允许重试；
* 重复登记报错。
"""

from __future__ import annotations

import asyncio

import pytest

from app.resources.base import Resource, ResourceState
from app.resources.errors import (
    ResourceAlreadyRegisteredError,
    ResourceNotReadyError,
    ResourceReleasedError,
)
from app.resources.manager import ResourceManager


class CountingResource(Resource):
    name = "counter"

    def __init__(self, delay: float = 0.02) -> None:
        super().__init__()
        self.delay = delay
        self.start_calls = 0
        self.stop_calls = 0

    async def startup(self) -> None:
        self.start_calls += 1
        await asyncio.sleep(self.delay)

    async def shutdown(self) -> None:
        self.stop_calls += 1
        await asyncio.sleep(0)


class FailingResource(Resource):
    name = "failing"

    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    async def startup(self) -> None:
        self.attempts += 1
        if self.attempts == 1:
            raise RuntimeError("startup failed")

    async def shutdown(self) -> None:
        pass


@pytest.mark.asyncio
async def test_concurrent_startup_initializes_once() -> None:
    manager = ResourceManager()
    resource = CountingResource()
    manager.register(resource)

    await asyncio.gather(*(manager.startup_all() for _ in range(50)))

    assert resource.start_calls == 1
    assert resource.state is ResourceState.READY
    assert manager.get("counter") is resource


@pytest.mark.asyncio
async def test_get_before_startup_rejected_as_not_ready() -> None:
    manager = ResourceManager()
    manager.register(CountingResource())

    with pytest.raises(ResourceNotReadyError) as exc:
        manager.get("counter")
    assert "尚未就绪" in str(exc.value)


@pytest.mark.asyncio
async def test_get_during_startup_rejected_as_not_ready() -> None:
    manager = ResourceManager()
    resource = CountingResource(delay=0.05)
    manager.register(resource)

    task = asyncio.create_task(manager.startup_all())
    await asyncio.sleep(0.01)  # 等待进入 STARTING
    with pytest.raises(ResourceNotReadyError):
        manager.get("counter")
    await task
    assert manager.get("counter") is resource


@pytest.mark.asyncio
async def test_get_after_shutdown_rejected_as_released() -> None:
    manager = ResourceManager()
    resource = CountingResource()
    manager.register(resource)
    await manager.startup_all()
    await manager.shutdown_all()

    with pytest.raises(ResourceReleasedError) as exc:
        manager.get("counter")
    assert "已释放" in str(exc.value)


@pytest.mark.asyncio
async def test_not_ready_and_released_are_distinct() -> None:
    fresh = ResourceManager()
    fresh.register(CountingResource())
    with pytest.raises(ResourceNotReadyError):
        fresh.get("counter")

    used = ResourceManager()
    used.register(CountingResource())
    await used.startup_all()
    await used.shutdown_all()
    with pytest.raises(ResourceReleasedError):
        used.get("counter")


@pytest.mark.asyncio
async def test_shutdown_is_idempotent() -> None:
    manager = ResourceManager()
    resource = CountingResource()
    manager.register(resource)
    await manager.startup_all()

    await manager.shutdown_all()
    await manager.shutdown_all()
    await manager.shutdown_all()

    assert resource.stop_calls == 1
    assert resource.state is ResourceState.RELEASED


@pytest.mark.asyncio
async def test_shutdown_without_startup_does_not_raise() -> None:
    manager = ResourceManager()
    manager.register(CountingResource())
    # 未启动直接关闭：不报错
    await manager.shutdown_all()
    assert manager.state_of("counter") is ResourceState.RELEASED


@pytest.mark.asyncio
async def test_failed_startup_allows_retry() -> None:
    manager = ResourceManager()
    failing = FailingResource()
    manager.register(failing)

    with pytest.raises(RuntimeError, match="startup failed"):
        await manager.startup_all()
    assert failing.state is ResourceState.CREATED
    # _started 未置位，允许再次整体启动
    await manager.startup_all()
    assert failing.state is ResourceState.READY
    assert failing.attempts == 2


@pytest.mark.asyncio
async def test_duplicate_registration_rejected() -> None:
    manager = ResourceManager()
    manager.register(CountingResource())
    with pytest.raises(ResourceAlreadyRegisteredError):
        manager.register(CountingResource())


@pytest.mark.asyncio
async def test_snapshot_reports_states() -> None:
    manager = ResourceManager()
    manager.register(CountingResource())
    assert manager.snapshot() == {"counter": "created"}
    await manager.startup_all()
    assert manager.snapshot() == {"counter": "ready"}
