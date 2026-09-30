"""分层配置包。"""

from __future__ import annotations

from app.config.errors import (
    ConfigError,
    ConfigTypeError,
    ConfigValidationError,
    DeprecatedConfigError,
    MissingConfigError,
    UnknownConfigKeyError,
)
from app.config.loader import load_settings, resolve_config_path, resolve_environment
from app.config.schema import AppConfig, FieldSpec

__all__ = [
    "AppConfig",
    "ConfigError",
    "ConfigTypeError",
    "ConfigValidationError",
    "DeprecatedConfigError",
    "FieldSpec",
    "MissingConfigError",
    "UnknownConfigKeyError",
    "load_settings",
    "resolve_config_path",
    "resolve_environment",
]
