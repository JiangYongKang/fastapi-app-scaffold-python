"""Configuration loading errors with distinguishable causes.

Each concrete error carries a stable ``reason`` string so callers (and tests)
can branch on the failure category without parsing message text.
"""

from __future__ import annotations


class ConfigError(Exception):
    """Base class for all configuration errors."""

    reason: str = "config_error"

    def __init__(self, message: str, *, key: str | None = None) -> None:
        super().__init__(message)
        self.key = key


class MissingConfigError(ConfigError):
    """A required configuration field has no value."""

    reason = "missing"


class ConfigTypeError(ConfigError):
    """A configuration value cannot be converted to the declared type."""

    reason = "type"


class ConfigValidationError(ConfigError):
    """A value has the right type but is illegal."""

    reason = "value"


class UnknownConfigKeyError(ConfigError):
    """A configuration key is not declared in the schema."""

    reason = "unknown_key"


class DeprecatedConfigError(ConfigError):
    """A removed/deprecated configuration key is still in use."""

    reason = "deprecated"
