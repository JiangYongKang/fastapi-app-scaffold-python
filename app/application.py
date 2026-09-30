"""应用装配：配置加载、资源生命周期、路由挂载。"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from app.config.schema import AppConfig
from app.resources.manager import ResourceManager
from app.routing.registry import RouteRegistry


def build_app(
    config_path: str | None = None,
    environment: str | None = None,
    environ: dict[str, str] | None = None,
) -> FastAPI:
    """构建并返回可运行的 FastAPI 应用（启动期完成全部校验）。"""
    raise NotImplementedError


def create_app() -> FastAPI:
    """uvicorn / ASGI 入口使用的工厂。"""
    raise NotImplementedError
