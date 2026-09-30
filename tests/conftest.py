"""pytest 公共夹具。

第三方库（starlette/anyio 测试客户端）的弃用告警通过 pyproject.toml
的 [pytest].filterwarnings 统一忽略，不在各用例中分散处理。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _quiet_httpx() -> Iterator[None]:
    """压低 httpx 的请求日志，避免污染测试输出。"""
    logger = logging.getLogger("httpx")
    saved = logger.level
    logger.setLevel(logging.WARNING)
    yield
    logger.setLevel(saved)


@pytest.fixture()
def tmp_config(tmp_path):
    """生成一个临时配置文件并返回写入函数。"""

    def _write(content: str) -> str:
        path = tmp_path / "config.toml"
        path.write_text(content, encoding="utf-8")
        return str(path)

    return _write
