"""Per-module router registration with eager prefix/path conflict detection.

Modules register their :class:`fastapi.APIRouter` with a prefix; conflicts
are raised as :class:`RouteConflictError` *at registration/startup time*
rather than letting later registrations silently shadow earlier ones:

* two modules using the same prefix;
* a static path segment clashing with a ``{param}`` segment at the same
  position (e.g. ``/users/me`` vs ``/users/{id}``);
* the same full method+path served by two routes (regardless of which
  module they come from).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from fastapi import APIRouter, FastAPI
from starlette.routing import Route

from app.core.errors import RouteConflictError

logger = logging.getLogger("app.routing")

_PARAM_SEGMENT = re.compile(r"^\{[^/}]+\}$")


def _normalize_prefix(prefix: str) -> str:
    prefix = prefix.strip()
    if not prefix:
        return ""
    if not prefix.startswith("/"):
        prefix = "/" + prefix
    return prefix.rstrip("/")


def _segments(path: str) -> tuple[str, ...]:
    return tuple(seg for seg in path.split("/") if seg)


def _segments_clash(a: str, b: str) -> bool:
    """True when one segment is static and the other is a path parameter."""
    a_param = bool(_PARAM_SEGMENT.match(a))
    b_param = bool(_PARAM_SEGMENT.match(b))
    return a_param != b_param


@dataclass(frozen=True)
class Registration:
    name: str
    prefix: str
    router: APIRouter


class RouterRegistry:
    def __init__(self) -> None:
        self._items: list[Registration] = []
        self._prefix_owners: dict[str, str] = {}
        # (method, path-segments) -> owner module for exact duplicate checks
        self._route_index: dict[tuple[str, tuple[str, ...]], str] = {}

    # -- registration -------------------------------------------------------

    def register(
        self, router: APIRouter, *, prefix: str = "", name: str = ""
    ) -> None:
        module = name or getattr(router, "__module__", "anonymous")
        norm = _normalize_prefix(prefix)

        # Only non-empty prefixes claim a namespace: multiple modules may be
        # mounted at root, their concrete routes are still de-duplicated.
        if norm and norm in self._prefix_owners:
            raise RouteConflictError(
                f"module '{module}' tries to mount prefix '{norm or '/'}' "
                f"but it is already owned by module "
                f"'{self._prefix_owners[norm]}'"
            )

        # Param-vs-static clashes with every previously mounted prefix.
        new_segs = _segments(norm)
        for prev_reg in self._items:
            prev_segs = _segments(prev_reg.prefix)
            if len(prev_segs) != len(new_segs):
                continue
            for a, b in zip(prev_segs, new_segs):
                if _segments_clash(a, b):
                    raise RouteConflictError(
                        f"prefix '{norm or '/'}' from module '{module}' "
                        f"clashes with prefix '{prev_reg.prefix or '/'}' "
                        f"from module '{prev_reg.name}': static segment "
                        f"against path parameter at position {list(new_segs).index(b)}"
                    )

        # Check the concrete routes contributed by this router.
        for route in router.routes:
            if not isinstance(route, Route):
                continue
            full_path = norm + route.path
            full_segs = _segments(full_path)
            for method in route.methods or ():
                if method in ("HEAD", "OPTIONS"):
                    # FastAPI auto-generates these; not independent endpoints.
                    continue
                key = (method, full_segs)
                if key in self._route_index:
                    raise RouteConflictError(
                        f"route {method} {full_path} from module '{module}' "
                        f"duplicates the same route already registered by "
                        f"module '{self._route_index[key]}'"
                    )
                # Param-vs-static clash against earlier concrete routes.
                for (prev_method, prev_segs), owner in self._route_index.items():
                    if prev_method != method or len(prev_segs) != len(full_segs):
                        continue
                    for a, b in zip(prev_segs, full_segs):
                        if _segments_clash(a, b):
                            raise RouteConflictError(
                                f"route {method} {full_path} from module "
                                f"'{module}' clashes with route from module "
                                f"'{owner}' at segment '{b}'"
                            )
                self._route_index[key] = module

        self._items.append(Registration(name=module, prefix=norm, router=router))
        if norm:
            self._prefix_owners[norm] = module
        logger.info("registered module '%s' at prefix '%s'", module, norm or "/")

    # -- mounting -----------------------------------------------------------

    def mount(self, app: FastAPI) -> None:
        for reg in self._items:
            app.include_router(reg.router, prefix=reg.prefix)
            logger.info(
                "mounted module '%s' under prefix '%s'",
                reg.name,
                reg.prefix or "/",
            )

    @property
    def registrations(self) -> tuple[Registration, ...]:
        return tuple(self._items)
