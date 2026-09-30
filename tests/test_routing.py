"""Router registration conflicts and the unified error envelope."""

from __future__ import annotations

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.core.errors import RouteConflictError
from app.core.router_registry import RouterRegistry


def _empty_handler() -> dict:
    return {}


def _router(path: str, method: str = "GET", module: str = "m") -> APIRouter:
    router = APIRouter()
    getattr(router, method.lower())(path, name=f"{module}-{path}-{method}")(
        _empty_handler
    )
    return router


def test_duplicate_prefix_fails_at_registration():
    registry = RouterRegistry()
    registry.register(_router("/a", module="one"), prefix="/api", name="one")
    with pytest.raises(RouteConflictError) as exc:
        registry.register(_router("/b", module="two"), prefix="/api", name="two")
    message = str(exc.value)
    assert "'/api'" in message
    assert "one" in message and "two" in message


def test_duplicate_full_path_at_root_fails_instead_of_shadowing():
    registry = RouterRegistry()
    registry.register(_router("/ping", module="first"), prefix="", name="first")
    with pytest.raises(RouteConflictError) as exc:
        registry.register(_router("/ping", module="second"), prefix="", name="second")
    assert "GET /ping" in str(exc.value)


def test_static_vs_parameter_prefix_clash_fails():
    registry = RouterRegistry()
    registry.register(_router("", module="u"), prefix="/users/me", name="u")
    with pytest.raises(RouteConflictError):
        registry.register(_router("", module="u2"), prefix="/users/{id}", name="u2")


def test_static_vs_parameter_route_clash_fails():
    first = APIRouter()

    @first.get("/users/me")
    def me() -> dict:
        return {}

    second = APIRouter()

    @second.get("/users/{user_id}")
    def by_id(user_id: str) -> dict:
        return {}

    registry = RouterRegistry()
    registry.register(first, prefix="/v1", name="first")
    with pytest.raises(RouteConflictError):
        registry.register(second, prefix="/v1", name="second")


def test_distinct_modules_mount_without_false_positive(app_factory):
    app = app_factory(environ={"APP_ENV": "test"})
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/healthz").status_code == 200
        assert client.get("/api/counter").status_code == 200


def test_config_error_aborts_application_startup(clean_environ):
    from app.config.errors import DeprecatedConfigError
    from app.factory import create_app

    with pytest.raises(DeprecatedConfigError):
        create_app(environ={"APP_DEBUG": "1"})


# -- unified error envelope -------------------------------------------------


def test_all_error_shapes_share_one_envelope(app_factory):
    app = app_factory(environ={"APP_ENV": "test"})
    with TestClient(app) as client:
        not_found = client.get("/does-not-exist")
        validation = client.get("/api/counter/not-a-route")

    assert not_found.status_code == 404
    assert set(not_found.json()) == {"error"}
    assert not_found.json()["error"]["code"] == "not_found"
    assert validation.status_code == 404
    assert "code" in validation.json()["error"]


def test_validation_error_envelope(app_factory):
    app = app_factory(environ={"APP_ENV": "test"})

    @app.post("/typed")
    def _typed(body: dict) -> dict:
        return body

    # Malformed JSON body triggers request validation failure.
    with TestClient(app) as client:
        response = client.post(
            "/typed",
            content=b"not-json",
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert "fields" in body["error"]["details"]


def test_unexpected_exception_is_not_leaked(app_factory):
    app = app_factory(environ={"APP_ENV": "test"})

    @app.get("/boom")
    def _boom() -> dict:
        raise RuntimeError("secret internal detail XYZ")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert "secret internal detail XYZ" not in str(body)


def test_app_error_carries_distinct_codes(app_factory):
    app = app_factory(environ={"APP_ENV": "test"})
    with TestClient(app, raise_server_exceptions=False) as client:
        app.state.resources.shutdown()
        released = client.get("/api/counter")
    assert released.status_code == 503
    assert released.json()["error"]["code"] == "resource_released"
