"""Declarative configuration schema.

A schema describes every supported configuration key, its type, whether it is
required (no built-in default), an optional default value and an optional
domain validator. Removed/renamed keys live in :data:`DEPRECATED_KEYS` so that
old configuration is reported loudly instead of being silently ignored.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Env(str, Enum):
    DEV = "dev"
    TEST = "test"
    PROD = "prod"


# Sentinel meaning "no code-level default; the field is required".
MISSING: Any = object()

LOG_LEVELS = ("critical", "error", "warning", "info", "debug", "trace")


def _port_validator(value: Any) -> None:
    if not (1 <= int(value) <= 65535):
        raise ValueError("must be between 1 and 65535")


def _env_validator(value: Any) -> None:
    if value not in tuple(e.value for e in Env):
        raise ValueError(f"must be one of {tuple(e.value for e in Env)}")


def _log_level_validator(value: Any) -> None:
    choices = tuple(LOG_LEVELS)
    if value not in choices:
        raise ValueError(f"must be one of {choices}")


@dataclass(frozen=True)
class FieldSpec:
    """Declaration of a single configuration key."""

    key: str
    value_type: type
    default: Any = MISSING
    required: bool = False
    validator: Callable[[Any], None] | None = None

    @property
    def has_default(self) -> bool:
        return self.default is not MISSING


@dataclass
class Schema:
    fields: dict[str, FieldSpec] = field(default_factory=dict)

    def add(self, spec: FieldSpec) -> FieldSpec:
        if spec.key in self.fields:
            raise ValueError(f"duplicate config field: {spec.key}")
        self.fields[spec.key] = spec
        return spec

    def get(self, key: str) -> FieldSpec:
        return self.fields[key]

    def __contains__(self, key: object) -> bool:
        return key in self.fields


# Removed/renamed keys -> human-readable migration hint.
# Using one of these fails startup with DeprecatedConfigError.
DEPRECATED_KEYS: dict[str, str] = {
    "debug": (
        "renamed to 'service.debug'; set APP_SERVICE__DEBUG or "
        "[service] debug = ..."
    ),
    "log_level": (
        "renamed to 'server.log_level'; set APP_SERVER__LOG_LEVEL "
        "or [server] log_level = ..."
    ),
    "server.bind": "renamed to 'server.host'",
    "counter.start": "renamed to 'counter.initial'",
}


def build_schema() -> Schema:
    """The scaffold application's own configuration schema.

    Every field carries a code-level default so the app still works with no
    config file at all; ``required`` fields are supported by the loader for
    downstream projects that choose to make a value mandatory.
    """
    schema = Schema()
    schema.add(FieldSpec("service.name", str, default="fastapi-app-scaffold"))
    schema.add(FieldSpec("service.env", str, default=Env.DEV.value,
                         validator=_env_validator))
    schema.add(FieldSpec("service.debug", bool, default=False))
    schema.add(FieldSpec("server.host", str, default="127.0.0.1"))
    schema.add(FieldSpec("server.port", int, default=8000,
                         validator=_port_validator))
    schema.add(FieldSpec("server.log_level", str, default="info",
                         validator=_log_level_validator))
    schema.add(FieldSpec("counter.initial", int, default=0))
    return schema
