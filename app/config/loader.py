"""Layered configuration loader.

Precedence (later layers win)::

    code defaults  <  configs/default.toml  <  configs/<env>.toml
                    <  explicit --config-file  <  APP_* environment variables

Failure categories are distinguishable by exception class / ``reason``:

* :class:`MissingConfigError`       -- required key absent everywhere
* :class:`ConfigTypeError`          -- value cannot be converted to the type
* :class:`ConfigValidationError`    -- wrong type-wise but illegal value
* :class:`UnknownConfigKeyError`    -- key not declared in the schema
* :class:`DeprecatedConfigError`    -- removed/renamed key still in use

The effective configuration and the source that decided each value are
emitted through the ``app.config`` logger at INFO level.
"""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config.errors import (
    ConfigError,
    ConfigTypeError,
    ConfigValidationError,
    DeprecatedConfigError,
    MissingConfigError,
    UnknownConfigKeyError,
)
from app.config.schema import DEPRECATED_KEYS, Env, Schema, build_schema

logger = logging.getLogger("app.config")

ENV_PREFIX = "APP_"
ENV_SEP = "__"
# Environment variables consumed by the loader itself; never mapped to keys.
_RESERVED_ENV = ("APP_ENV", "APP_CONFIG_FILE")
_CONFIGS_DIR = Path(__file__).resolve().parents[2] / "configs"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class LoadedConfig:
    values: dict[str, Any]
    sources: dict[str, str]
    env: str


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"config file {path} is not valid TOML: {exc}") from None
    return data


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in data.items():
        dotted = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flat.update(_flatten(value, dotted))
        else:
            flat[dotted] = value
    return flat


def _env_key_to_dotted(env_name: str) -> str:
    # APP_SERVER__LOG_LEVEL -> server.log_level
    return env_name[len(ENV_PREFIX):].lower().replace(ENV_SEP, ".")


def _dotted_key_to_env(key: str) -> str:
    # server.log_level -> APP_SERVER__LOG_LEVEL
    return ENV_PREFIX + key.replace(".", ENV_SEP).upper()


def _coerce(raw: Any, spec: Any) -> Any:
    """Convert a raw value (TOML/string) to the declared field type."""
    wanted = spec.value_type
    if wanted is bool:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            low = raw.strip().lower()
            if low in _TRUE:
                return True
            if low in _FALSE:
                return False
        raise ConfigTypeError(
            f"config '{spec.key}' expects a boolean, got {raw!r}",
            key=spec.key,
        )
    if wanted is int:
        # bool is a subclass of int; reject it deliberately.
        if isinstance(raw, int) and not isinstance(raw, bool):
            return raw
        if isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
            return int(raw.strip())
        raise ConfigTypeError(
            f"config '{spec.key}' expects an integer, got {raw!r}",
            key=spec.key,
        )
    if wanted is float:
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            return float(raw)
        if isinstance(raw, str):
            try:
                return float(raw.strip())
            except ValueError:
                pass
        raise ConfigTypeError(
            f"config '{spec.key}' expects a number, got {raw!r}",
            key=spec.key,
        )
    if wanted is str:
        if isinstance(raw, str):
            return raw
        raise ConfigTypeError(
            f"config '{spec.key}' expects a string, got {raw!r}",
            key=spec.key,
        )
    if isinstance(raw, wanted):
        return raw
    raise ConfigTypeError(
        f"config '{spec.key}' expects {wanted.__name__}, got {raw!r}",
        key=spec.key,
    )


def _check_keys(flat: dict[str, Any], schema: Schema, origin: str) -> None:
    """Reject deprecated and unknown keys before any value is consumed."""
    for key in flat:
        if key in DEPRECATED_KEYS:
            raise DeprecatedConfigError(
                f"config '{key}' (from {origin}) is deprecated: "
                f"{DEPRECATED_KEYS[key]}",
                key=key,
            )
        if key not in schema:
            hint = _dotted_key_to_env(key)
            raise UnknownConfigKeyError(
                f"unknown config key '{key}' (from {origin}); "
                f"check spelling or remove it (env form: {hint})",
                key=key,
            )


def _read_env_overrides(
    environ: dict[str, str], schema: Schema
) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for env_name, raw_value in environ.items():
        if not env_name.startswith(ENV_PREFIX) or env_name in _RESERVED_ENV:
            continue
        key = _env_key_to_dotted(env_name)
        if key in DEPRECATED_KEYS:
            raise DeprecatedConfigError(
                f"environment variable {env_name} maps to deprecated config "
                f"'{key}': {DEPRECATED_KEYS[key]}",
                key=key,
            )
        if key not in schema:
            raise UnknownConfigKeyError(
                f"environment variable {env_name} maps to unknown config "
                f"key '{key}'",
                key=key,
            )
        overrides[key] = raw_value
    return overrides


def _resolve_env(env: str | None, environ: dict[str, str]) -> str:
    selected = env or environ.get("APP_ENV", Env.DEV.value)
    valid = tuple(e.value for e in Env)
    if selected not in valid:
        raise ConfigValidationError(
            f"invalid environment {selected!r}; expected one of {valid} "
            f"(set APP_ENV)",
            key="service.env",
        )
    return selected


def _build_layers(
    env: str,
    config_file: str | None,
    environ: dict[str, str],
    schema: Schema,
    *,
    use_env_file: bool = True,
) -> list[tuple[str, dict[str, Any]]]:
    layers: list[tuple[str, dict[str, Any]]] = []

    default_path = _CONFIGS_DIR / "default.toml"
    if default_path.is_file():
        flat = _flatten(_load_toml(default_path))
        _check_keys(flat, schema, str(default_path))
        layers.append((f"file:{default_path}", flat))

    if use_env_file:
        env_path = _CONFIGS_DIR / f"{env}.toml"
        if env_path.is_file():
            flat = _flatten(_load_toml(env_path))
            _check_keys(flat, schema, str(env_path))
            layers.append((f"file:{env_path}", flat))

    explicit = config_file or environ.get("APP_CONFIG_FILE")
    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            path = Path.cwd() / path
        flat = _flatten(_load_toml(path))
        _check_keys(flat, schema, str(path))
        layers.append((f"file:{path}", flat))

    env_overrides = _read_env_overrides(environ, schema)
    if env_overrides:
        layers.append(("environment", env_overrides))

    return layers


def load_config_with_sources(
    env: str | None = None,
    config_file: str | None = None,
    environ: dict[str, str] | None = None,
    schema: Schema | None = None,
    *,
    log: bool = True,
    use_env_file: bool = True,
) -> LoadedConfig:
    schema = schema or build_schema()
    environ = dict(os.environ if environ is None else environ)
    selected_env = _resolve_env(env, environ)
    layers = _build_layers(
        selected_env,
        config_file,
        environ,
        schema,
        use_env_file=use_env_file,
    )

    values: dict[str, Any] = {}
    sources: dict[str, str] = {}

    # Code defaults first; each following layer may override.
    for key, spec in schema.fields.items():
        if spec.has_default:
            values[key] = spec.default
            sources[key] = "code-default"

    for origin, flat in layers:
        for key, raw in flat.items():
            spec = schema.get(key)
            value = _coerce(raw, spec)
            if spec.validator is not None:
                try:
                    spec.validator(value)
                except ValueError as exc:
                    raise ConfigValidationError(
                        f"invalid value for config '{key}': {exc}; "
                        f"got {value!r} (from {origin})",
                        key=key,
                    ) from None
            values[key] = value
            sources[key] = origin

    for key, spec in schema.fields.items():
        if key not in values and (spec.required or not spec.has_default):
            env_name = _dotted_key_to_env(key)
            raise MissingConfigError(
                f"missing required config '{key}'; provide it in a "
                f"config file or the {env_name} environment variable",
                key=key,
            )

    # Keep service.env consistent with the selected environment; APP_ENV is
    # the selector and wins over any value set for service.env in a file.
    values["service.env"] = selected_env
    sources["service.env"] = (
        "environment:APP_ENV" if environ.get("APP_ENV") else "env-selector(default)"
    )

    if log:
        logger.info(
            "config precedence: code defaults < %s/default.toml < "
            "%s/<env>.toml < explicit file < %s* environment variables",
            _CONFIGS_DIR,
            _CONFIGS_DIR,
            ENV_PREFIX,
        )
        for origin, _ in layers:
            logger.info("config layer applied: %s", origin)
        for key in sorted(values):
            logger.info(
                "effective config %s = %r  [%s]",
                key,
                values[key],
                sources[key],
            )

    return LoadedConfig(values=values, sources=sources, env=selected_env)


def load_config(
    env: str | None = None,
    config_file: str | None = None,
    environ: dict[str, str] | None = None,
    schema: Schema | None = None,
    *,
    log: bool = True,
    use_env_file: bool = True,
) -> dict[str, Any]:
    """Load, validate and return the effective configuration as a dict."""
    return load_config_with_sources(
        env,
        config_file,
        environ,
        schema,
        log=log,
        use_env_file=use_env_file,
    ).values
