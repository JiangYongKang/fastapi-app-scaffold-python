"""Default module preserving the template's out-of-the-box Hello World."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["root"])


@router.get("/")
def read_root(request: Request) -> dict:
    config = getattr(request.app.state, "config", {})
    name = config.get("service.name", "fastapi-app-scaffold")
    env = config.get("service.env", "dev")
    return {"Hello": "World", "service": name, "env": env}


@router.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
