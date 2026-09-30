"""Shared pytest fixtures."""

from __future__ import annotations

import logging

import pytest

from app.factory import create_app


@pytest.fixture(autouse=True)
def _ensure_debug_logging(caplog):
    """Make caplog capture the config decision logs for every test."""
    caplog.set_level(logging.DEBUG, logger="app")


@pytest.fixture
def clean_environ(monkeypatch):
    """Environment with no APP_* overrides and a neutral working directory."""
    for name in list(__import__("os").environ):
        if name.startswith("APP_"):
            monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def app_factory():
    apps = []

    def _factory(**kwargs):
        app = create_app(**kwargs)
        apps.append(app)
        return app

    yield _factory

    for app in apps:
        resources = getattr(app.state, "resources", None)
        if resources is not None:
            resources.shutdown()
