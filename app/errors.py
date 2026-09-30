"""统一错误响应结构与全局异常处理器。"""

from __future__ import annotations

from typing import Any


class AppHTTPError(Exception):
    """应用层可预期错误的基类，携带统一错误码与 HTTP 状态码。"""

    status_code: int = 400
    code: str = "bad_request"

    def __init__(self, message: str, *, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


def register_exception_handlers(app: Any) -> None:
    """为 FastAPI 应用注册统一异常处理：所有错误返回同一结构。"""
    raise NotImplementedError
