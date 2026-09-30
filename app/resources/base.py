"""共享资源的抽象基类与生命周期状态。

资源状态机::

    CREATED ──startup()──> STARTING ──成功──> READY
                                └──失败──> CREATED（允许重试）
    READY ──shutdown()──> STOPPING ──> RELEASED

约定：

* 同一种资源在整个应用内只登记一次、只初始化一次；
* ``startup`` / ``shutdown`` 由 :class:`ResourceManager` 统一驱动，
  子类只实现资源本身的建立与释放逻辑。
"""

from __future__ import annotations

import enum


class ResourceState(enum.Enum):
    CREATED = "created"
    STARTING = "starting"
    READY = "ready"
    STOPPING = "stopping"
    RELEASED = "released"


class Resource:
    """共享资源基类。

    子类必须设置 :attr:`name`，并实现 :meth:`startup` 与 :meth:`shutdown`。
    初始化得到的连接/客户端可保存在任意属性上，请求侧通过依赖获取实例。
    """

    name: str = ""

    def __init__(self) -> None:
        self.state: ResourceState = ResourceState.CREATED

    async def startup(self) -> None:
        """建立资源。仅在资源处于 CREATED 时会被管理器调用。"""
        raise NotImplementedError

    async def shutdown(self) -> None:
        """释放资源。仅在资源处于 READY 时会被管理器调用。"""
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<{type(self).__name__} name={self.name!r} state={self.state.value}>"
