"""Shared resource lifecycle guarantees."""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from app.core.errors import (
    ResourceNotReadyError,
    ResourceReleasedError,
)
from app.core.resources import ResourceRegistry, ResourceState


class RecordingResource:
    def __init__(self) -> None:
        self.opens = 0
        self.closes = 0

    def open(self) -> None:
        self.opens += 1

    def close(self) -> None:
        self.closes += 1


class SlowResource(RecordingResource):
    def __init__(self, gate: threading.Event) -> None:
        super().__init__()
        self._gate = gate

    def open(self) -> None:
        self._gate.wait(timeout=2)
        super().open()


class FailingResource:
    def __init__(self) -> None:
        self.opens = 0
        self.closes = 0

    def open(self) -> None:
        self.opens += 1
        raise RuntimeError("cannot open")

    def close(self) -> None:
        self.closes += 1


def test_acquire_before_startup_is_rejected_as_not_ready():
    reg = ResourceRegistry()
    reg.register("r", RecordingResource())
    with pytest.raises(ResourceNotReadyError) as exc:
        reg.acquire("r")
    assert exc.value.code == "resource_not_ready"
    assert exc.value.details["state"] == "new"


def test_concurrent_initialization_opens_resource_once():
    gate = threading.Event()
    resource = SlowResource(gate)
    reg = ResourceRegistry()
    reg.register("slow", resource)

    errors: list[Exception] = []

    def init() -> None:
        try:
            reg.initialize()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=init) for _ in range(8)]
    for t in threads:
        t.start()
    gate.set()
    for t in threads:
        t.join()

    assert not errors
    assert resource.opens == 1
    assert reg.acquire("slow") is resource


def test_shutdown_is_idempotent_and_requests_are_rejected_as_released():
    reg = ResourceRegistry()
    resource = RecordingResource()
    reg.register("r", resource)
    reg.initialize()

    reg.shutdown()
    reg.shutdown()  # must not raise
    assert resource.closes == 1

    with pytest.raises(ResourceReleasedError) as exc:
        reg.acquire("r")
    assert exc.value.code == "resource_released"
    assert exc.value.details["state"] == "released"
    assert ResourceNotReadyError is not ResourceReleasedError


def test_shutdown_without_startup_does_nothing():
    reg = ResourceRegistry()
    reg.register("r", RecordingResource())
    reg.shutdown()  # must not raise
    assert reg.state("r") is ResourceState.RELEASED


def test_failed_open_is_reported_as_not_ready_and_shutdown_safe():
    reg = ResourceRegistry()
    reg.register("boom", FailingResource())
    with pytest.raises(RuntimeError):
        reg.initialize()
    with pytest.raises(ResourceNotReadyError) as exc:
        reg.acquire("boom")
    assert exc.value.details["state"] == "failed"
    reg.shutdown()  # failed resource must not break shutdown


def test_duplicate_registration_is_rejected():
    reg = ResourceRegistry()
    reg.register("r", RecordingResource())
    with pytest.raises(RuntimeError):
        reg.register("r", RecordingResource())


# -- HTTP-level integration -------------------------------------------------


def test_request_during_shutdown_window_returns_envelope(app_factory):
    app = app_factory(environ={"APP_ENV": "test"})
    client = TestClient(app)
    with client:  # lifespan starts resources
        ok = client.get("/api/counter")
        assert ok.status_code == 200
    # After exit the lifespan released resources; without a lifespan context
    # the request still gets the standard envelope for a released resource.
    app.state.resources.shutdown()
    response = client.get("/api/counter")
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "resource_released"
    assert body["error"]["details"]["resource"] == "counter"
