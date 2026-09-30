"""Application factory: wires configuration, resources and module routers.

Configuration errors raised here abort application creation/startup instead
of being deferred to the first request.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config.loader import load_config_with_sources
from app.core.error_handlers import register_exception_handlers
from app.core.resources import ResourceRegistry
from app.core.router_registry import RouterRegistry
from app.modules.counter.resources import CounterResource
from app.modules.counter.router import COUNTER_RESOURCE
from app.modules.counter.router import router as counter_router
from app.modules.root import router as root_router

logger = logging.getLogger("app")


def build_resource_registry(config: dict) -> ResourceRegistry:
    registry = ResourceRegistry()
    registry.register(
        COUNTER_RESOURCE,
        CounterResource(initial=config.get("counter.initial", 0)),
    )
    return registry


def build_router_registry() -> RouterRegistry:
    registry = RouterRegistry()
    # Root module keeps the template's default "/" behaviour.
    registry.register(root_router, prefix="", name="root")
    registry.register(counter_router, prefix="/api", name="counter")
    return registry


def create_app(
    config: dict | None = None,
    *,
    env: str | None = None,
    config_file: str | None = None,
    environ: dict[str, str] | None = None,
) -> FastAPI:
    if config is None:
        loaded = load_config_with_sources(env, config_file, environ)
        config = loaded.values
        effective_env = loaded.env
    else:
        effective_env = config.get("service.env", os.environ.get("APP_ENV", "dev"))

    debug = bool(config.get("service.debug", False))
    log_level = str(config.get("server.log_level", "info")).upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    resources = build_resource_registry(config)
    routers = build_router_registry()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> Iterator[None]:
        # Eagerly initialize before accepting traffic; failures abort startup.
        resources.initialize()
        try:
            yield
        finally:
            # Idempotent: safe even if startup failed or called repeatedly.
            resources.shutdown()

    app = FastAPI(
        title=str(config.get("service.name", "fastapi-app-scaffold")),
        debug=debug,
        lifespan=lifespan,
    )
    app.state.config = config
    app.state.resources = resources
    app.state.env = effective_env

    register_exception_handlers(app, debug=debug)
    # RouteConflictError is raised here, before the app starts serving.
    routers.mount(app)
    app.state.routers = routers

    logger.info("application '%s' created for env=%s", app.title, effective_env)
    return app
