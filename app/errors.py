"""统一错误响应结构与全局异常处理器。

所有对外错误都使用同一信封::

    {
      "error": {
        "code": "resource_not_ready",      # 机器可判定的错误码
        "message": "资源 'db' 尚未就绪...",  # 人类可读说明
        "details": {...}                    # 可选的结构化上下文
      }
    }

处理范围：

* :class:`AppHTTPError`：应用层显式抛出的可预期错误；
* 资源域错误（未就绪 / 已释放 / 未登记）：统一 503/500，code 可区分；
* FastAPI/Starlette 的请求校验错误、HTTPException：归入同一信封；
* 兜底 ``Exception``：只返回通用 500，**不把底层异常原样透出**，
  真实异常仅记录到服务端日志。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.resources.errors import (
    ResourceNotReadyError,
    ResourceReleasedError,
    ResourceNotFoundError,
)

logger = logging.getLogger("app.errors")


class AppHTTPError(Exception):
    """应用层可预期错误的基类，携带统一错误码与 HTTP 状态码。"""

    status_code: int = 400
    code: str = "bad_request"

    def __init__(self, message: str, *, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


def _error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


def _json_error(
    status_code: int, code: str, message: str, details: Any = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=_error_body(code, message, details),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """注册全部异常处理器，保证错误响应结构统一。"""

    @app.exception_handler(AppHTTPError)
    async def _handle_app_error(
        _request: Request, exc: AppHTTPError
    ) -> JSONResponse:
        return _json_error(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(ResourceNotReadyError)
    async def _handle_not_ready(
        _request: Request, exc: ResourceNotReadyError
    ) -> JSONResponse:
        return _json_error(503, "resource_not_ready", str(exc))

    @app.exception_handler(ResourceReleasedError)
    async def _handle_released(
        _request: Request, exc: ResourceReleasedError
    ) -> JSONResponse:
        return _json_error(503, "resource_released", str(exc))

    @app.exception_handler(ResourceNotFoundError)
    async def _handle_resource_not_found(
        _request: Request, exc: ResourceNotFoundError
    ) -> JSONResponse:
        # 装配错误属于服务端问题，不向客户端泄露内部资源名以外的信息
        logger.error("请求了未登记的资源: %s", exc)
        return _json_error(500, "resource_not_configured", "资源未正确配置")

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _json_error(
            422,
            "validation_error",
            "请求参数校验失败",
            details={"errors": exc.errors()},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = {
            400: "bad_request",
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            405: "method_not_allowed",
            409: "conflict",
            429: "too_many_requests",
        }.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else "请求错误"
        return _json_error(exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def _handle_unexpected(
        request: Request, exc: Exception
    ) -> JSONResponse:
        # 底层异常只记录日志，绝不原样返回给客户端
        logger.exception(
            "未处理异常 %s %s: %s", request.method, request.url.path, exc
        )
        return _json_error(
            500, "internal_error", "服务器内部错误，请稍后重试"
        )
