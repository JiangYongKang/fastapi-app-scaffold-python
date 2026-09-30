"""共享资源的抽象基类与生命周期状态。"""

from __future__ import annotations

import enum
from typing import Any


class ResourceState(enum.Enum):
    CREATED = "created"
    STARTING = "starting"
    READY = "ready"
    STOPPING = "stopping"
    RELEASED = "released"


class Resource:
    """共享资源基类：子类实现 startup/shutdown。"""

    name: str = ""

    def __init__(self) -> None:
        self.state = ResourceState.CREATED

    async def startup(self) -> None:
        raise NotImplementedError

    async def shutdown(self) -> None:
        raise NotImplementedError
