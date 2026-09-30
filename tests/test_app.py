"""端到端应用测试。

覆盖：
* 开箱即用：GET / 仍返回 {"Hello": "World"}；
* 配置非法在启动阶段失败，且失败原因类型可区分；
* 资源未就绪 / 已释放时请求被拒绝，错误 code 可区分；
* 所有错误响应共用同一信封，底层异常不原样透出；
* 启动日志打印实际生效配置与判定依据；
* 构建期路由冲突直接抛出（不被吞掉）。
"""

from __future__ import annotations

import logging

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

import app.application as application
from app.application import build_app
from app.config.errors import (
    ConfigTypeError,
    ConfigValidationError,
    DeprecatedConfigError,
    UnknownConfigKeyError,
)
from app.resources.base import ResourceState
from app.routing.registry import RouteConflictError


def _app(**kwargs) -> object:
    kwargs.setdefault("environment", "no-such-env")
    kwargs.setdefault("environ", {})
    return build_app(**kwargs)


# ------------------------------------------------------------- 开箱即用
def test_root_keeps_out_of_the_box_behavior() -> None:
    with TestClient(_app()) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json() == {"Hello": "World"}


def test_health_and_info_endpoints() -> None:
    app = _app()
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        ready = client.get("/readyz").json()
        assert ready["ready"] is True
        assert ready["resources"]["app_info"] == "ready"

        info = client.get("/api/info").json()
        assert info["name"] == "fastapi-app-scaffold"
        assert info["environment"] == "development"


# -------------------------------------------------- 启动期配置失败可区分
def test_invalid_config_types_fail_at_startup(tmp_config) -> None:
    path = tmp_config('[server]\nport = "abc"\n')
    with pytest.raises(ConfigTypeError):
        build_app(config_path=path, environ={})


def test_invalid_config_value_fails_at_startup(tmp_config) -> None:
    path = tmp_config('[app]\nlog_level = "NOPE"\n')
    with pytest.raises(ConfigValidationError):
        build_app(config_path=path, environ={})


def test_deprecated_config_fails_at_startup(tmp_config) -> None:
    path = tmp_config('debug = false\n')
    with pytest.raises(DeprecatedConfigError):
        build_app(config_path=path, environ={})


def test_unknown_config_fails_at_startup(tmp_config) -> None:
    path = tmp_config('typo_key = 1\n')
    with pytest.raises(UnknownConfigKeyError):
        build_app(config_path=path, environ={})


def test_env_override_takes_effect(tmp_config) -> None:
    path = tmp_config('[app]\nname = "file-name"\n')
    app = build_app(
        config_path=path,
        environ={"APP_NAME": "env-name", "API_PREFIX": "/custom"},
    )
    with TestClient(app) as client:
        assert client.get("/custom/info").json()["name"] == "env-name"
        # 旧前缀下不再挂载
        assert client.get("/api/info").status_code == 404


# -------------------------------------------------- 路由冲突在构建期暴露
def test_route_conflict_fails_build(monkeypatch) -> None:
    def conflicting_registry(config):  # noqa: ANN001
        registry = application.RouteRegistry(api_prefix=config.api_prefix)
        a = APIRouter(); a.get("/x")(lambda: None)
        b = APIRouter(); b.get("/")(lambda: None)
        registry.register_module("a", "/", a)
        registry.register_module("b", "/x", b)  # 与 a 的 GET x 冲突
        return registry

    monkeypatch.setattr(application, "_build_registry", conflicting_registry)
    with pytest.raises(RouteConflictError, match="GET /api/x"):
        build_app(environment="no-such-env", environ={})


# ----------------------------------------- 资源未就绪/已释放：可区分拒绝
def test_request_rejected_when_resource_not_ready() -> None:
    app = _app()
    with TestClient(app) as client:
        app.state.resources.get("app_info")  # 此时 READY，正常
        # 模拟资源尚未就绪
        app.state.resources._resources["app_info"].state = (
            ResourceState.CREATED
        )
        resp = client.get("/api/info")
        assert resp.status_code == 503
        body = resp.json()
        assert body["error"]["code"] == "resource_not_ready"
        assert "尚未就绪" in body["error"]["message"]


def test_request_rejected_when_resource_released() -> None:
    app = _app()
    with TestClient(app) as client:
        # 模拟应用已进入关闭流程、资源被释放
        app.state.resources._resources["app_info"].state = (
            ResourceState.RELEASED
        )
        resp = client.get("/api/info")
        assert resp.status_code == 503
        body = resp.json()
        assert body["error"]["code"] == "resource_released"
        assert "已释放" in body["error"]["message"]


def test_not_ready_and_released_have_distinct_codes() -> None:
    codes = set()
    for state in (ResourceState.CREATED, ResourceState.RELEASED):
        app = _app()
        with TestClient(app) as client:
            app.state.resources._resources["app_info"].state = state
            codes.add(client.get("/api/info").json()["error"]["code"])
    assert codes == {"resource_not_ready", "resource_released"}


# ------------------------------------------------------------- 错误信封
def test_404_uses_unified_envelope() -> None:
    with TestClient(_app()) as client:
        body = client.get("/does-not-exist").json()
        assert set(body) == {"error"}
        assert body["error"]["code"] == "not_found"
        assert body["error"]["message"]


def test_422_uses_unified_envelope() -> None:
    app = _app()
    router = APIRouter()

    @router.get("/needs-int/{value}")
    def needs_int(value: int):  # noqa: ANN202
        return {"value": value}

    app.include_router(router)
    with TestClient(app) as client:
        resp = client.get("/needs-int/not-int")
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "validation_error"
        assert "errors" in body["error"]["details"]


def test_unexpected_exception_is_not_leaked() -> None:
    app = _app()
    router = APIRouter()

    @router.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail: db password=hunter2")

    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/boom")
        assert resp.status_code == 500
        body = resp.json()
        assert body["error"]["code"] == "internal_error"
        assert "hunter2" not in str(body)
        assert "RuntimeError" not in str(body)


# ------------------------------------------------------------- 启动日志
def test_startup_logs_effective_config_and_sources(tmp_config, caplog) -> None:
    path = tmp_config('[server]\nport = 9100\n')
    with caplog.at_level(logging.INFO, logger="app"):
        build_app(
            config_path=path,
            environ={"APP_NAME": "logged-name"},
        )
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "logged-name" in text          # 环境变量生效值
    assert "9100" in text                 # 文件生效值
    assert "env:APP_NAME" in text         # 判定依据：来自环境变量
    assert "file:" in text                # 判定依据：来自文件
    assert "default" in text              # 判定依据：来自默认值


def test_shutdown_is_idempotent_via_lifespan() -> None:
    app = _app()
    with TestClient(app):
        pass
    # lifespan 退出后再次关闭不应抛错
    import asyncio
    asyncio.run(app.state.resources.shutdown_all())
