"""示例业务模块：演示如何通过依赖安全地使用共享资源。

挂载后提供 ``GET {api.prefix}/info``。资源未就绪/已释放时，
依赖会抛出资源域异常，最终返回统一结构的 503。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.resources.app_info import AppInfoResource
from app.resources.deps import resource_dependency

MODULE_NAME = "info"
PREFIX = "/info"

router = APIRouter()


@router.get("", tags=[MODULE_NAME])
def get_info(
    resource: AppInfoResource = Depends(resource_dependency("app_info")),
) -> dict[str, str]:
    assert resource.info is not None  # READY 状态下必有值
    return resource.info
