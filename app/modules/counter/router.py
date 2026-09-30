"""Demo routes built on top of the shared counter resource."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.resources import ResourceRegistry

COUNTER_RESOURCE = "counter"

router = APIRouter(tags=["counter"])


def _registry(request: Request) -> ResourceRegistry:
    return request.app.state.resources


@router.get("/counter")
def get_counter(request: Request) -> dict:
    counter = _registry(request).acquire(COUNTER_RESOURCE)
    return {"value": counter.value}


@router.post("/counter/increment")
def increment_counter(request: Request) -> dict:
    counter = _registry(request).acquire(COUNTER_RESOURCE)
    return {"value": counter.increment()}
