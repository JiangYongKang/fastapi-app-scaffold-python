"""Configuration layering, precedence and distinguishable failure causes."""

from __future__ import annotations

import pytest

from app.config import loader
from app.config.errors import (
    ConfigError,
    ConfigTypeError,
    ConfigValidationError,
    DeprecatedConfigError,
    MissingConfigError,
    UnknownConfigKeyError,
)
from app.config.schema import FieldSpec, Schema

EMPTY_ENV: dict[str, str] = {}


def test_code_defaults_work_without_any_file():
    cfg = loader.load_config(
        environ=EMPTY_ENV, log=False, use_env_file=False
    )
    assert cfg["service.name"] == "fastapi-app-scaffold"
    assert cfg["server.port"] == 8000
    assert cfg["service.debug"] is False


def test_dev_env_file_is_applied_by_default():
    # With no APP_ENV the dev layer (configs/dev.toml) is merged in.
    cfg = loader.load_config(environ=EMPTY_ENV, log=False)
    assert cfg["service.debug"] is True
    assert cfg["server.log_level"] == "debug"


def test_env_overrides_have_highest_precedence(caplog, tmp_path, monkeypatch):
    cfg_file = tmp_path / "over.toml"
    cfg_file.write_text('[server]\nport = 7000\n', encoding="utf-8")

    with caplog.at_level("INFO", logger="app.config"):
        cfg = loader.load_config_with_sources(
            environ={"APP_SERVER__PORT": "9999", "APP_ENV": "dev"},
            config_file=str(cfg_file),
            log=True,
        )

    assert cfg.values["server.port"] == 9999
    assert cfg.sources["server.port"] == "environment"
    # The decision basis for every key is present in the logs.
    records = [r.getMessage() for r in caplog.records]
    assert any("effective config server.port = 9999" in m for m in records)
    assert any("config layer applied: environment" in m for m in records)


def test_file_overrides_default_and_its_source_is_logged(tmp_path, caplog):
    cfg_file = tmp_path / "over.toml"
    cfg_file.write_text('[server]\nport = 7100\n', encoding="utf-8")
    with caplog.at_level("INFO", logger="app.config"):
        loaded = loader.load_config_with_sources(
            environ=EMPTY_ENV, config_file=str(cfg_file)
        )
    assert loaded.values["server.port"] == 7100
    assert loaded.sources["server.port"].endswith("over.toml")
    assert any("7100" in r.getMessage() for r in caplog.records)


def test_environment_specific_file_layer(monkeypatch, tmp_path):
    # When APP_CONFIG_FILE is absent the <env>.toml layer is selected.
    cfg = loader.load_config(environ={"APP_ENV": "prod"}, log=False)
    assert cfg["service.env"] == "prod"
    assert cfg["server.host"] == "0.0.0.0"


def test_missing_required_field_is_distinguishable():
    schema = Schema()
    schema.add(FieldSpec("secret.token", str, required=True))
    with pytest.raises(ConfigError) as exc_info:
        loader.load_config(
            environ=EMPTY_ENV, schema=schema, log=False, use_env_file=False
        )
    assert isinstance(exc_info.value, MissingConfigError)
    assert exc_info.value.reason == "missing"
    assert exc_info.value.key == "secret.token"


@pytest.mark.parametrize(
    "env_value,expected",
    [
        ({"APP_SERVER__PORT": "not-an-int"}, ConfigTypeError),
        ({"APP_SERVICE__DEBUG": "maybe"}, ConfigTypeError),
    ],
)
def test_type_errors_are_distinguishable(env_value, expected):
    with pytest.raises(ConfigError) as exc_info:
        loader.load_config(environ=env_value, log=False)
    assert type(exc_info.value) is expected
    assert exc_info.value.reason == "type"


@pytest.mark.parametrize(
    "env_value",
    [
        {"APP_SERVER__PORT": "70000"},
        {"APP_SERVER__PORT": "0"},
        {"APP_SERVER__LOG_LEVEL": "verbose"},
        {"APP_ENV": "staging"},
    ],
)
def test_invalid_values_are_distinguishable(env_value):
    with pytest.raises(ConfigError) as exc_info:
        loader.load_config(environ=env_value, log=False)
    assert isinstance(exc_info.value, ConfigValidationError)
    assert exc_info.value.reason == "value"


def test_unknown_key_is_distinguishable_from_value_error():
    with pytest.raises(UnknownConfigKeyError) as exc_info:
        loader.load_config(environ={"APP_SERVER__HORT": "127.0.0.1"}, log=False)
    assert exc_info.value.reason == "unknown_key"
    assert "server.hort" in str(exc_info.value)


def test_deprecated_key_in_environment_is_reported_with_migration_hint():
    with pytest.raises(DeprecatedConfigError) as exc_info:
        loader.load_config(environ={"APP_DEBUG": "true"}, log=False)
    assert exc_info.value.reason == "deprecated"
    assert "service.debug" in str(exc_info.value)
    assert exc_info.value.key == "debug"


def test_deprecated_key_in_file_is_reported(tmp_path):
    cfg_file = tmp_path / "old.toml"
    cfg_file.write_text('[counter]\nstart = 5\n', encoding="utf-8")
    with pytest.raises(DeprecatedConfigError) as exc_info:
        loader.load_config(
            environ=EMPTY_ENV, config_file=str(cfg_file), log=False
        )
    assert exc_info.value.reason == "deprecated"
    assert "counter.initial" in str(exc_info.value)


def test_unknown_key_in_file_is_reported(tmp_path):
    cfg_file = tmp_path / "bad.toml"
    cfg_file.write_text('[server]\nports = 8000\n', encoding="utf-8")
    with pytest.raises(UnknownConfigKeyError):
        loader.load_config(
            environ=EMPTY_ENV, config_file=str(cfg_file), log=False
        )


def test_missing_config_file_fails_at_startup():
    with pytest.raises(ConfigError):
        loader.load_config(
            environ=EMPTY_ENV,
            config_file="/nonexistent/path/missing.toml",
            log=False,
        )


def test_boolean_type_coercion():
    for truthy in ("1", "true", "YES", "on"):
        cfg = loader.load_config(
            environ={"APP_SERVICE__DEBUG": truthy}, log=False
        )
        assert cfg["service.debug"] is True
    for falsy in ("0", "false", "NO", "off"):
        cfg = loader.load_config(
            environ={"APP_SERVICE__DEBUG": falsy}, log=False
        )
        assert cfg["service.debug"] is False
