"""Shared resource lifecycle management.

Guarantees:

* Each named resource is opened exactly once; concurrent callers racing into
  startup block until initialization finishes -- they never cause a second
  ``open()`` of the same resource.
* Requests arriving before startup completes get
  :class:`ResourceNotReadyError` (``resource_not_ready``).
* Requests arriving after shutdown get :class:`ResourceReleasedError`
  (``resource_released``) -- the two states are distinguishable.
* ``initialize()`` and ``shutdown()`` are idempotent: calling shutdown twice
  (or shutdown without startup) never raises.
"""

from __future__ import annotations

import logging
import threading
from enum import Enum
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger("app.resources")


class ResourceState(str, Enum):
    NEW = "new"
    READY = "ready"
    RELEASED = "released"
    FAILED = "failed"


@runtime_checkable
class Resource(Protocol):
    def open(self) -> None: ...
    def close(self) -> None: ...


class ResourceRegistry:
    def __init__(self) -> None:
        self._resources: dict[str, Resource] = {}
        self._states: dict[str, ResourceState] = {}
        self._ready_events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        # Serializes the "am I the startup leader?" decision.
        self._gate = threading.Lock()
        self._init_started = False
        self._init_finished = threading.Event()

    # -- registration -------------------------------------------------------

    def register(self, name: str, resource: Resource) -> None:
        """Register a resource before startup. Fails on duplicate names."""
        with self._lock:
            if self._init_started:
                raise RuntimeError(
                    f"cannot register resource '{name}' after startup"
                )
            if name in self._resources:
                raise RuntimeError(f"duplicate resource name: {name}")
            if not isinstance(resource, Resource):
                raise TypeError(
                    f"resource '{name}' must implement open()/close()"
                )
            self._resources[name] = resource
            self._states[name] = ResourceState.NEW
            event = threading.Event()
            # Before startup nothing is being opened; do not block waiters.
            event.set()
            self._ready_events[name] = event

    # -- lifecycle ----------------------------------------------------------

    def initialize(self) -> None:
        """Open every registered resource exactly once. Idempotent.

        Concurrent callers block until the first (leader) caller finishes;
        a resource is therefore never opened twice.
        """
        with self._gate:
            if self._init_started:
                leader = False
            else:
                self._init_started = True
                leader = True

        if not leader:
            self._init_finished.wait()
            return

        try:
            for name, resource in self._resources.items():
                event = self._ready_events[name]
                event.clear()
                try:
                    logger.info("opening resource: %s", name)
                    resource.open()
                    self._states[name] = ResourceState.READY
                    logger.info("resource ready: %s", name)
                except Exception:
                    self._states[name] = ResourceState.FAILED
                    logger.exception("resource failed to open: %s", name)
                    raise
                finally:
                    event.set()
        finally:
            self._init_finished.set()

    def shutdown(self) -> None:
        """Close every ready resource. Safe to call zero or many times."""
        if self._init_started:
            # If startup is in progress in another thread, let it finish.
            self._init_finished.wait()
        else:
            logger.info("shutdown called before startup; nothing to close")

        for name in reversed(list(self._resources)):
            state = self._states[name]
            if state is not ResourceState.READY:
                logger.info(
                    "skip closing resource %s (state=%s)", name, state.value
                )
                self._states[name] = ResourceState.RELEASED
                continue
            try:
                logger.info("closing resource: %s", name)
                self._resources[name].close()
            except Exception:
                logger.exception("error while closing resource: %s", name)
            finally:
                self._states[name] = ResourceState.RELEASED

    # -- access -------------------------------------------------------------

    @property
    def initialized(self) -> bool:
        return self._init_started and self._init_finished.is_set()

    def state(self, name: str) -> ResourceState:
        if name not in self._resources:
            raise KeyError(f"unknown resource: {name}")
        return self._states[name]

    def acquire(self, name: str, *, wait: bool = False) -> Any:
        """Return the live resource, or raise a distinguishable AppError.

        With ``wait=True`` a request arriving during startup blocks until the
        resource becomes ready. With the default ``wait=False`` it is rejected
        immediately as ``resource_not_ready``.
        """
        from app.core.errors import (
            ResourceNotReadyError,
            ResourceReleasedError,
        )

        if name not in self._resources:
            raise KeyError(f"unknown resource: {name}")

        if wait and self._states[name] in (
            ResourceState.NEW,
            ResourceState.FAILED,
        ):
            self._ready_events[name].wait()

        state = self._states[name]
        if state is ResourceState.READY:
            return self._resources[name]
        if state is ResourceState.RELEASED:
            raise ResourceReleasedError(
                f"resource '{name}' has already been released",
                details={"resource": name, "state": state.value},
            )
        if state is ResourceState.FAILED:
            raise ResourceNotReadyError(
                f"resource '{name}' failed to initialize",
                details={"resource": name, "state": state.value},
            )
        raise ResourceNotReadyError(
            f"resource '{name}' is not ready yet",
            details={"resource": name, "state": state.value},
        )
