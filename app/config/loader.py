"""分层配置合并：默认值 < 配置文件 < 环境变量。

判定顺序（从低到高，后者覆盖前者）：

1. ``FieldSpec.default`` 内置默认值
2. ``configs/<environment>.toml``（或显式指定的文件）
3. 进程环境变量（白名单读取 schema 中声明的变量）

每一层都可能被高优先级层覆盖；每个字段最终来自哪一层会被记录下来，
供启动日志打印"实际生效配置与判定依据"。

启动期失败分类（互相可区分）：

* :class:`DeprecatedConfigError` —— 使用了已废弃的旧键/旧环境变量
* :class:`UnknownConfigKeyError` —— 配置文件出现 schema 未定义的键
* :class:`MissingConfigError` —— 必填字段在所有层都缺失
* :class:`ConfigTypeError` —— 值无法转换为声明类型
* :class:`ConfigValidationError` —— 类型正确但取值非法
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from app.config.errors import (
    ConfigTypeError,
    ConfigValidationError,
    DeprecatedConfigError,
    MissingConfigError,
    UnknownConfigKeyError,
)
from app.config.schema import (
    AppConfig,
    ConfigKind,
    DEPRECATED_ENVS,
    DEPRECATED_FILE_KEYS,
    FIELDS,
    FIELD_BY_ENV,
    FIELD_BY_KEY,
    REQUIRED,
    FieldSpec,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "configs"

_TRUE_TOKENS = frozenset({"1", "true", "yes", "on"})
_FALSE_TOKENS = frozenset({"0", "false", "no", "off"})


def resolve_environment(
    explicit: str | None, environ: dict[str, str] | None
) -> str:
    """决定用于挑选配置文件的环境名：显式参数 > 环境变量 > development。"""
    env_map = os.environ if environ is None else environ
    return explicit or env_map.get("APP_ENVIRONMENT") or "development"


def resolve_config_path(
    app_env: str | None = None,
    explicit_path: str | None = None,
    environ: dict[str, str] | None = None,
) -> Path | None:
    """解析配置文件路径。

    显式给定时必须存在，否则抛 :class:`FileNotFoundError`；
    未显式给定时查找 ``configs/<environment>.toml``，存在则返回，
    不存在则返回 ``None``（允许只靠默认值+环境变量运行）。
    """
    if explicit_path is not None:
        path = Path(explicit_path)
        if not path.is_file():
            raise FileNotFoundError(f"配置文件不存在: {path}")
        return path

    environment = resolve_environment(app_env, environ)
    candidate = CONFIG_DIR / f"{environment}.toml"
    return candidate if candidate.is_file() else None


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """把 TOML 的嵌套表展平成点分层级键。"""
    flat: dict[str, Any] = {}
    for key, value in data.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten(value, dotted))
        else:
            flat[dotted] = value
    return flat


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _coerce(spec: FieldSpec, raw: Any, source: str) -> Any:
    """把原始值转换为字段声明类型；失败抛 ConfigTypeError。"""
    where = f"配置项 {spec.key!r}（来源: {source}）"
    try:
        if spec.kind is ConfigKind.STR:
            if not isinstance(raw, str):
                raise ConfigTypeError(
                    f"{where} 的值类型为 {type(raw).__name__}，"
                    f"期望字符串 str"
                )
            value = raw.strip()
        elif spec.kind is ConfigKind.INT:
            if isinstance(raw, bool):
                raise ConfigTypeError(
                    f"{where} 的值类型为 bool，期望整数 int"
                )
            if isinstance(raw, int):
                value = raw
            elif isinstance(raw, str):
                token = raw.strip()
                try:
                    value = int(token, 10)
                except ValueError:
                    raise ConfigTypeError(
                        f"{where} 的字符串值 {raw!r} 无法解析为整数"
                    ) from None
            else:
                raise ConfigTypeError(
                    f"{where} 的值类型为 {type(raw).__name__}，"
                    f"期望整数 int"
                )
        elif spec.kind is ConfigKind.BOOL:
            if isinstance(raw, bool):
                value = raw
            elif isinstance(raw, str):
                token = raw.strip().lower()
                if token in _TRUE_TOKENS:
                    value = True
                elif token in _FALSE_TOKENS:
                    value = False
                else:
                    raise ConfigTypeError(
                        f"{where} 的字符串值 {raw!r} 无法解析为布尔值，"
                        f"可选: true/false/1/0/yes/no/on/off"
                    )
            else:
                raise ConfigTypeError(
                    f"{where} 的值类型为 {type(raw).__name__}，"
                    f"期望布尔值 bool"
                )
        else:  # pragma: no cover - 防御性分支
            raise ConfigTypeError(f"{where} 声明了未知类型 {spec.kind!r}")
    except ConfigTypeError:
        raise
    return value


def _validate(spec: FieldSpec, value: Any, source: str) -> Any:
    """对已完成类型转换的值做取值约束校验；可返回归一化后的值。"""
    where = f"配置项 {spec.key!r}（来源: {source}，值: {value!r}）"

    if spec.kind is ConfigKind.STR:
        if not value:
            raise ConfigValidationError(f"{where} 不允许为空字符串")
        if spec.key == "api.prefix" and not value.startswith("/"):
            raise ConfigValidationError(
                f"{where} 必须以 '/' 开头"
            )
        # log_level 大小写不敏感：先归一化为大写再做枚举校验
        if spec.key == "app.log_level":
            value = value.upper()
            where = f"配置项 {spec.key!r}（来源: {source}，值: {value!r}）"
        if spec.choices is not None and value not in spec.choices:
            allowed = ", ".join(spec.choices)
            raise ConfigValidationError(
                f"{where} 不在允许的取值范围内，可选: {allowed}"
            )

    if spec.kind is ConfigKind.INT:
        if spec.ge is not None and value < spec.ge:
            raise ConfigValidationError(
                f"{where} 不能小于 {spec.ge}"
            )
        if spec.le is not None and value > spec.le:
            raise ConfigValidationError(
                f"{where} 不能大于 {spec.le}"
            )
        if spec.choices is not None and value not in spec.choices:
            allowed = ", ".join(str(c) for c in spec.choices)
            raise ConfigValidationError(
                f"{where} 不在允许的取值范围内，可选: {allowed}"
            )

    return value


def _check_deprecated_env(env_map: dict[str, str]) -> None:
    offenders = [
        (name, replacement)
        for name, replacement in DEPRECATED_ENVS.items()
        if name in env_map and env_map[name] != ""
    ]
    if offenders:
        lines = [
            f"环境变量 {name!r} 已废弃，请改用 {new!r}"
            for name, new in offenders
        ]
        raise DeprecatedConfigError("；".join(lines))


def _check_deprecated_and_unknown_file(file_values: dict[str, Any]) -> None:
    deprecated = [
        (key, replacement)
        for key, replacement in DEPRECATED_FILE_KEYS.items()
        if key in file_values
    ]
    if deprecated:
        lines = [
            f"配置文件键 {key!r} 已废弃，请改用 {new!r}"
            for key, new in deprecated
        ]
        raise DeprecatedConfigError("；".join(lines))

    unknown = sorted(key for key in file_values if key not in FIELD_BY_KEY)
    if unknown:
        allowed = ", ".join(sorted(FIELD_BY_KEY))
        raise UnknownConfigKeyError(
            f"配置文件出现未定义的配置项: {', '.join(unknown)}；"
            f"已知配置项: {allowed}"
        )


def load_settings(
    config_path: str | None = None,
    environment: str | None = None,
    environ: dict[str, str] | None = None,
) -> tuple[AppConfig, dict[str, dict[str, Any]]]:
    """加载并校验配置。

    返回 ``(AppConfig, sources)``，``sources`` 记录每个字段最终生效的值、
    来源层以及三层原始值，用于启动日志说明判定依据。

    任何非法情况都在本函数内抛出 :class:`ConfigError` 子类，
    即"启动阶段就失败"。
    """
    env_map = os.environ if environ is None else environ

    # 1) 废弃环境变量优先检查（显式拒绝，绝不静默忽略）
    _check_deprecated_env(env_map)

    # 2) 解析并读取配置文件
    path = resolve_config_path(environment, config_path, env_map)
    raw_file = _flatten(_read_toml(path)) if path is not None else {}
    file_label = f"file:{path}" if path is not None else "file:<未加载>"
    _check_deprecated_and_unknown_file(raw_file)

    resolved: dict[str, dict[str, Any]] = {}
    raw_layers: dict[str, dict[str, Any]] = {
        "default": {},
        "file": dict(raw_file),
        "env": {},
    }

    # 3) 逐字段按优先级合并：默认值 < 文件 < 环境变量
    for spec in FIELDS:
        default_value = None if spec.default is REQUIRED else spec.default
        raw_layers["default"][spec.key] = default_value

        raw_env = env_map.get(spec.env)
        if raw_env is not None and raw_env.strip() != "":
            raw_value, source = raw_env, f"env:{spec.env}"
            raw_layers["env"][spec.key] = raw_env
        elif spec.key in raw_file:
            raw_value, source = raw_file[spec.key], file_label
        elif spec.default is not REQUIRED:
            raw_value, source = spec.default, "default"
        else:
            raise MissingConfigError(
                f"必填配置项 {spec.key!r} 缺失：默认值、配置文件"
                f"（{file_label}）和环境变量 {spec.env!r} 均未提供。"
                f"说明: {spec.help}"
            )

        converted = _coerce(spec, raw_value, source)
        converted = _validate(spec, converted, source)
        resolved[spec.key] = {"value": converted, "source": source}

    config = AppConfig(
        app_name=resolved["app.name"]["value"],
        environment=resolved["app.environment"]["value"],
        debug=resolved["app.debug"]["value"],
        log_level=resolved["app.log_level"]["value"],
        api_prefix=resolved["api.prefix"]["value"],
        host=resolved["server.host"]["value"],
        port=resolved["server.port"]["value"],
    )

    for entry in resolved.values():
        entry["raw_layers"] = raw_layers
    return config, resolved
