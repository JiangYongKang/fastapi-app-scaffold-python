"""示例共享资源：应用元信息持有者。

它演示一个标准资源的写法：

* ``name`` 唯一标识；
* :meth:`startup` 只做一次建立动作；
* :meth:`shutdown` 释放并保证可重复安全调用（由管理器保证只调用一次）。

新项目可复制此文件实现数据库连接池、HTTP 客户端等真实资源。
"""

from __future__ import annotations

import logging

from app.resources.base import Resource

logger = logging.getLogger("app.resources.app_info")


class AppInfoResource(Resource):
    name = "app_info"

    def __init__(self, app_name: str, environment: str) -> None:
        super().__init__()
        self._app_name = app_name
        self._environment = environment
        self.info: dict[str, str] | None = None

    async def startup(self) -> None:
        # 真实项目中这里可能是建连接池等一次性动作
        logger.info("初始化资源 app_info")
        self.info = {
            "name": self._app_name,
            "environment": self._environment,
        }

    async def shutdown(self) -> None:
        logger.info("释放资源 app_info")
        self.info = None
