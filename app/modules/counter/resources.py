"""Demo shared resource: an in-memory counter.

Shows the resource contract (``open``/``close``) and keeps its own
initialization state so callers can observe the lifecycle in logs.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("app.modules.counter")


class CounterResource:
    def __init__(self, initial: int = 0) -> None:
        self._initial = initial
        self.value: int | None = None

    def open(self) -> None:
        logger.info("CounterResource.open(initial=%s)", self._initial)
        self.value = self._initial

    def close(self) -> None:
        logger.info("CounterResource.close()")
        self.value = None

    def increment(self) -> int:
        if self.value is None:
            raise RuntimeError("counter has not been opened")
        self.value += 1
        return self.value
