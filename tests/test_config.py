"""配置层测试。

覆盖：
* 分层优先级：默认值 < 文件 < 环境变量；
* 缺字段 / 类型错误 / 取值非法 / 废弃键 / 未知键 五类失败原因可区分；
* 来源追踪正确，供日志说明判定依据。
"""

from __future__ import annotations

import pytest

from app.config.errors import (
    ConfigTypeError,
    ConfigValidationError,
    DeprecatedConfigError,
    MissingConfigError,
    UnknownConfigKeyError,
)
from app.config.loader import load_settings
from app.config.schema import REQUIRED, FIELDS

EMPTY_ENV: dict[str, str] = {}


# ------------------------------------------------------------- 优先级合并
def test_defaults_when_no_file(tmp_config) -> None:
    # 指向一个真实存在但内容为空的文件，避免读到 configs/development.toml
    path = tmp_config("")
    cfg, sources = load_settings(config_path=path, environ=EMPTY_ENV)
    assert cfg.app_name == "fastapi-app-scaffold"
    assert cfg.environment == "development"
    assert cfg.debug is False
    assert cfg.log_level == "INFO"
    assert cfg.api_prefix == "/api"
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8000
    assert all(v["source"] == "default" for v in sources.values())


def test_file_overrides_default(tmp_config) -> None:
    path = tmp_config(
        '[app]\nname = "file-name"\ndebug = true\n'
        '[server]\nport = 9001\nhost = "0.0.0.0"\n'
        '[api]\nprefix = "/v2"\n'
    )
    cfg, sources = load_settings(config_path=path, environ=EMPTY_ENV)
    assert cfg.app_name == "file-name"
    assert cfg.debug is True
    assert cfg.port == 9001
    assert cfg.host == "0.0.0.0"
    assert cfg.api_prefix == "/v2"
    assert sources["app.name"]["source"] == f"file:{path}"
    assert sources["server.port"]["source"] == f"file:{path}"


def test_env_overrides_file(tmp_config) -> None:
    path = tmp_config('[server]\nport = 9001\n[app]\nname = "file-name"\n')
    cfg, sources = load_settings(
        config_path=path,
        environ={"SERVER_PORT": "1234", "APP_NAME": "env-name"},
    )
    assert cfg.port == 1234
    assert cfg.app_name == "env-name"
    assert sources["server.port"]["source"] == "env:SERVER_PORT"
    assert sources["app.name"]["source"] == "env:APP_NAME"
    # 未被环境变量覆盖的字段仍来自文件
    assert sources["server.host"]["source"] == "default"


def test_empty_env_string_is_treated_as_unset(tmp_config) -> None:
    path = tmp_config('[server]\nport = 9001\n')
    cfg, _ = load_settings(config_path=path, environ={"SERVER_PORT": "   "})
    assert cfg.port == 9001


def test_log_level_case_insensitive(tmp_config) -> None:
    path = tmp_config('[app]\nlog_level = "warning"\n')
    cfg, _ = load_settings(config_path=path, environ=EMPTY_ENV)
    assert cfg.log_level == "WARNING"


def test_env_bool_parsing(tmp_config) -> None:
    path = tmp_config("")
    for token, expected in [
        ("true", True), ("1", True), ("yes", True), ("ON", True),
        ("false", False), ("0", False), ("no", False), ("off", False),
    ]:
        cfg, _ = load_settings(
            config_path=path, environ={"APP_DEBUG": token}
        )
        assert cfg.debug is expected


# ------------------------------------------------------------- 缺字段
def test_missing_required_field(tmp_config) -> None:
    from app.config.schema import FieldSpec, ConfigKind

    required = FieldSpec(
        key="db.dsn",
        kind=ConfigKind.STR,
        env="DB_DSN",
        help="数据库连接串",
    )
    path = tmp_config("")
    with pytest.raises(MissingConfigError) as exc:
        load_settings(
            config_path=path,
            environ=EMPTY_ENV,
            fields=(required,),
            deprecated_file_keys={},
            deprecated_envs={},
        )
    message = str(exc.value)
    assert "db.dsn" in message
    assert "DB_DSN" in message  # 提示应告诉调用方该设哪个环境变量


def test_required_field_satisfied_by_env(tmp_config) -> None:
    from app.config.schema import FieldSpec, ConfigKind
    from dataclasses import replace

    # 复制内置 server.host 但去掉默认值，环境变量提供即可通过
    host_spec = next(s for s in FIELDS if s.key == "server.host")
    required = replace(host_spec, default=REQUIRED)
    path = tmp_config("")
    cfg, sources = load_settings(
        config_path=path,
        environ={"SERVER_HOST": "10.0.0.1"},
        fields=tuple(
            required if s.key == "server.host" else s for s in FIELDS
        ),
    )
    assert cfg.host == "10.0.0.1"
    assert sources["server.host"]["source"] == "env:SERVER_HOST"


# ------------------------------------------------------------- 类型错误
def test_type_error_int_from_file(tmp_config) -> None:
    path = tmp_config('[server]\nport = "not-an-int"\n')
    with pytest.raises(ConfigTypeError) as exc:
        load_settings(config_path=path, environ=EMPTY_ENV)
    assert "server.port" in str(exc.value)
    assert "整数" in str(exc.value)


def test_type_error_int_from_env(tmp_config) -> None:
    path = tmp_config("")
    with pytest.raises(ConfigTypeError) as exc:
        load_settings(config_path=path, environ={"SERVER_PORT": "abc"})
    assert "env:SERVER_PORT" in str(exc.value)


def test_type_error_bool(tmp_config) -> None:
    path = tmp_config("")
    with pytest.raises(ConfigTypeError) as exc:
        load_settings(config_path=path, environ={"APP_DEBUG": "maybe"})
    assert "布尔值" in str(exc.value)


def test_type_error_wrong_toml_type(tmp_config) -> None:
    # TOML 中给字符串字段一个数组
    path = tmp_config('[app]\nname = [1, 2]\n')
    with pytest.raises(ConfigTypeError) as exc:
        load_settings(config_path=path, environ=EMPTY_ENV)
    assert "app.name" in str(exc.value)


# ------------------------------------------------------------- 取值非法
def test_validation_error_port_too_large(tmp_config) -> None:
    path = tmp_config('[server]\nport = 70000\n')
    with pytest.raises(ConfigValidationError) as exc:
        load_settings(config_path=path, environ=EMPTY_ENV)
    assert "不能大于" in str(exc.value)


def test_validation_error_port_too_small(tmp_config) -> None:
    path = tmp_config("")
    with pytest.raises(ConfigValidationError):
        load_settings(config_path=path, environ={"SERVER_PORT": "0"})


def test_validation_error_bad_choice(tmp_config) -> None:
    path = tmp_config('[app]\nlog_level = "CHATTY"\n')
    with pytest.raises(ConfigValidationError) as exc:
        load_settings(config_path=path, environ=EMPTY_ENV)
    assert "app.log_level" in str(exc.value)


def test_validation_error_prefix_must_start_slash(tmp_config) -> None:
    path = tmp_config("")
    with pytest.raises(ConfigValidationError) as exc:
        load_settings(config_path=path, environ={"API_PREFIX": "v1"})
    assert "必须以 '/' 开头" in str(exc.value)


def test_validation_error_empty_string(tmp_config) -> None:
    path = tmp_config('[app]\nname = "   "\n')
    with pytest.raises(ConfigValidationError) as exc:
        load_settings(config_path=path, environ=EMPTY_ENV)
    assert "不允许为空" in str(exc.value)


# ------------------------------------------------------------- 废弃项
def test_deprecated_file_key(tmp_config) -> None:
    path = tmp_config('debug = true\n')
    with pytest.raises(DeprecatedConfigError) as exc:
        load_settings(config_path=path, environ=EMPTY_ENV)
    assert "'debug'" in str(exc.value)
    assert "app.debug" in str(exc.value)


def test_deprecated_env_variable(tmp_config) -> None:
    path = tmp_config("")
    with pytest.raises(DeprecatedConfigError) as exc:
        load_settings(config_path=path, environ={"APP_PORT": "9000"})
    assert "APP_PORT" in str(exc.value)
    assert "SERVER_PORT" in str(exc.value)


# ------------------------------------------------------------- 未知键
def test_unknown_file_key(tmp_config) -> None:
    path = tmp_config('app.tpyo = 1\n')
    with pytest.raises(UnknownConfigKeyError) as exc:
        load_settings(config_path=path, environ=EMPTY_ENV)
    assert "app.tpyo" in str(exc.value)


def test_missing_file_explicit_path() -> None:
    with pytest.raises(FileNotFoundError):
        load_settings(config_path="/no/such/config.toml", environ=EMPTY_ENV)


# ------------------------------------------------------------- 错误可区分
def test_error_causes_are_distinct_types(tmp_config) -> None:
    cases = {
        ConfigTypeError: '[server]\nport = "x"\n',
        ConfigValidationError: '[server]\nport = 99999\n',
        DeprecatedConfigError: 'name = "x"\n',
        UnknownConfigKeyError: 'wat = 1\n',
    }
    seen: set[type[Exception]] = set()
    for exc_type, content in cases.items():
        with pytest.raises(exc_type):
            load_settings(config_path=tmp_config(content), environ=EMPTY_ENV)
        seen.add(exc_type)
    assert seen == set(cases)
