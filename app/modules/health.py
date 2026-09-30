"""健康检查模块。

``GET /healthz`` 不依赖任何共享资源，应用进程存活即可响应；
``GET /readyz`` 额外汇总各资源状态，用于就绪探针。
"""

from __future__ import annotations

from fastapi import APIRouter, Request

MODULE_NAME = "health"
PREFIX = "/"

router = APIRouter()


@router.get("/healthz", tags=[MODULE_NAME])
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", tags=[MODULE_NAME])
def readyz(request: Request) -> dict[str, object]:
    resources = request.app.state.resources.snapshot()
    ready = all(state == "ready" for state in resources.values())
    return {"ready": ready, "resources": resources}
