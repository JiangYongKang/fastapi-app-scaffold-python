"""pytest 公共夹具与噪音抑制。"""

from __future__ import annotations

import logging
import warnings
from collections.abc import Iterator

import pytest

# 屏蔽 TestClient 关于 httpx 的弃用告警噪音
warnings.filterwarnings("ignore", category=DeprecationWarning)


@pytest.fixture(autouse=True)
def _quiet_httpx() -> Iterator[None]:
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
