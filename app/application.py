"""应用装配：配置加载、资源生命周期、路由挂载、统一错误处理。

启动顺序（任一步失败都在"启动阶段"暴露，不会带病运行）：

1. 分层加载并校验配置（失败抛 :class:`ConfigError` 子类）；
2. 配置日志；
3. 创建 :class:`ResourceManager` 并登记资源；
4. 创建 :class:`RouteRegistry`，登记全部模块并做冲突检测；
5. 构建 FastAPI 应用、注册统一异常处理器、挂载路由；
6. lifespan 在运行期负责资源的启动与关闭。

运行 ``python main.py`` 或用 ``main:app`` 指向 ASGI 时，
默认加载 ``development`` 环境，保留开箱即用行为。
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import AsyncIterator

from fastapi import FastAPI

from app.config.loader import load_settings, resolve_config_path
from app.config.schema import AppConfig
from app.errors import register_exception_handlers
from app.modules import health, info, root
from app.resources.app_info import AppInfoResource
from app.resources.manager import ResourceManager
from app.routing.registry import RouteRegistry

logger = logging.getLogger("app")


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _log_effective_config(
    config: AppConfig,
    sources: dict[str, dict[str, object]],
    config_file: object,
) -> None:
    """打印实际生效的配置以及每个字段来自哪一层（判定依据）。"""
    logger.info("配置文件: %s", config_file)
    logger.info(
        "生效配置: app_name=%r environment=%r debug=%r log_level=%r "
        "api_prefix=%r host=%r port=%r",
        config.app_name,
        config.environment,
        config.debug,
        config.log_level,
        config.api_prefix,
        config.host,
        config.port,
    )
    for key in sorted(sources):
        logger.info("  %s = %r <- %s", key, sources[key]["value"],
                    sources[key]["source"])


def _register_system_modules(app: FastAPI, config: AppConfig) -> None:
    """挂载系统级路由（不套 api.prefix）。

    系统路由是脚手架固定部分：根路由 ``/``、健康探针 ``/healthz``、
    就绪探针 ``/readyz``，路径固定且互不重叠，直接挂载。
    业务模块才走 :class:`RouteRegistry` 的统一前缀与冲突检测。
    """
    app.include_router(root.router)
    app.include_router(health.router)


def _build_registry(config: AppConfig) -> RouteRegistry:
    """登记全部业务模块并在启动期完成冲突检测。"""
    registry = RouteRegistry(api_prefix=config.api_prefix)
    registry.register_module(info.MODULE_NAME, info.PREFIX, info.router)
    return registry


def build_app(
    config_path: str | None = None,
    environment: str | None = None,
    environ: dict[str, str] | None = None,
) -> FastAPI:
    """构建并返回 FastAPI 应用。

    参数主要供测试使用；生产留空即可，此时环境与配置路径按
    :mod:`app.config.loader` 的规则自行解析。
    """
    # 1) 配置（非法时直接抛出，FastAPI 应用对象都不会创建）
    config, sources = load_settings(config_path, environment, environ)
    env_map = os.environ if environ is None else environ
    config_file = resolve_config_path(environment, config_path, env_map)

    # 2) 日志
    _configure_logging(config.log_level)
    _log_effective_config(config, sources, config_file)

    # 3) 资源
    resources = ResourceManager()
    resources.register(AppInfoResource(config.app_name, config.environment))

    # 4) 路由登记与冲突检测（冲突在这里抛出 RouteConflictError）
    api_registry = _build_registry(config)

    # 5) 应用与异常处理
    app = FastAPI(title=config.app_name)
    app.state.config = config
    app.state.resources = resources
    register_exception_handlers(app)

    # 根路径系统路由直接挂载（不套 api.prefix）
    _register_system_modules(app, config)
    api_registry.mount_all(app)

    # 6) lifespan：资源随应用启动/关闭
    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await resources.startup_all()
        logger.info("应用启动完成，资源状态: %s", resources.snapshot())
        try:
            yield
        finally:
            await resources.shutdown_all()
            logger.info("应用已关闭")

    app.router.lifespan_context = lifespan
    return app


def create_app() -> FastAPI:
    """ASGI 入口工厂（``main:app`` / uvicorn 使用）。"""
    return build_app()
