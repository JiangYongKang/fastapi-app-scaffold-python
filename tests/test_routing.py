"""路由登记与冲突检测测试。

覆盖：
* 重复模块名；
* 重复模块前缀；
* 模块内 / 跨模块的"方法+路径"重复（含末尾斜杠差异）；
* 同路径不同方法不冲突；
* 挂载后路径可达，前缀统一生效。
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.routing.registry import RouteConflictError, RouteRegistry


def _router_with(*routes: tuple[str, str]) -> APIRouter:
    """用 (METHOD, PATH) 列表快速构造一个 router。"""
    router = APIRouter()
    for method, path in routes:
        getattr(router, method.lower())(path)(lambda: {"ok": True})
    return router


def test_duplicate_module_name_rejected() -> None:
    registry = RouteRegistry("/api")
    registry.register_module("m1", "/a", _router_with(("GET", "/")))
    with pytest.raises(RouteConflictError, match="模块名"):
        registry.register_module("m1", "/b", _router_with(("GET", "/")))


def test_duplicate_prefix_rejected() -> None:
    registry = RouteRegistry("/api")
    registry.register_module("m1", "/same", _router_with(("GET", "/a")))
    with pytest.raises(RouteConflictError, match="前缀") as exc:
        registry.register_module("m2", "/same", _router_with(("GET", "/b")))
    assert "'m1'" in str(exc.value)
    assert "'m2'" in str(exc.value)


def test_prefix_trailing_slash_normalized_conflict() -> None:
    registry = RouteRegistry("/api")
    registry.register_module("m1", "/same", _router_with(("GET", "/a")))
    with pytest.raises(RouteConflictError, match="前缀"):
        registry.register_module("m2", "/same/", _router_with(("GET", "/b")))


def test_duplicate_method_and_path_within_module() -> None:
    registry = RouteRegistry("/api")
    router = _router_with(("GET", "/things"), ("GET", "/things/"))
    with pytest.raises(RouteConflictError, match="GET /api/m/things"):
        registry.register_module("m", "/m", router)


def test_duplicate_method_and_path_across_root_modules() -> None:
    # 根前缀 "/" 模块的 /x 与 "/x" 前缀模块的 / 是同一路径
    registry = RouteRegistry("/api")
    registry.register_module(
        "root", "/", _router_with(("GET", "/x"))
    )
    with pytest.raises(RouteConflictError, match="同时被模块") as exc:
        registry.register_module(
            "x", "/x", _router_with(("GET", "/"))
        )
    assert "/api/x" in str(exc.value)


def test_same_path_different_method_is_allowed() -> None:
    registry = RouteRegistry("/api")
    registry.register_module(
        "m1", "/things", _router_with(("GET", "/"))
    )
    registry.register_module(
        "m2", "/other", _router_with(("POST", "/things"))
    )
    assert len(registry.registrations()) == 2


def test_bad_prefix_shape_rejected() -> None:
    registry = RouteRegistry("/api")
    with pytest.raises(RouteConflictError, match="必须以 '/' 开头"):
        registry.register_module("bad", "no-leading-slash",
                                 _router_with(("GET", "/")))


def test_mounted_paths_reachable() -> None:
    registry = RouteRegistry("/api")
    registry.register_module(
        "items", "/items", _router_with(("GET", ""), ("GET", "/{item_id}"))
    )
    app = FastAPI()
    registry.mount_all(app)
    client = TestClient(app)
    assert client.get("/api/items").status_code == 200
    assert client.get("/api/items/42").status_code == 200


def test_root_prefix_module_mounts_directly_under_api_prefix() -> None:
    registry = RouteRegistry("/api")
    registry.register_module("root", "/", _router_with(("GET", "/ping")))
    app = FastAPI()
    registry.mount_all(app)
    client = TestClient(app)
    assert client.get("/api/ping").status_code == 200
