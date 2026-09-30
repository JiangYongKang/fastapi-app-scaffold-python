"""健康检查模块：不依赖共享资源，随时可用。"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()
