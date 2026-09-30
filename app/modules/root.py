"""根模块：保留模板开箱即用的 ``GET /`` 行为。

该模块不挂在业务 API 前缀下，直接挂在根路径，
保证脚手架 ``python main.py`` 后访问 ``/`` 仍返回 ``{"Hello": "World"}``。
"""

from __future__ import annotations

from fastapi import APIRouter

MODULE_NAME = "root"
PREFIX = "/"

router = APIRouter()


@router.get("/", tags=[MODULE_NAME])
def read_root() -> dict[str, str]:
    return {"Hello": "World"}
