"""配置结构定义：字段清单、废弃键映射。

字段使用点分层级（如 ``app.debug``），每个字段显式声明：
类型、来源环境变量名、默认值（或必填）、取值约束。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ConfigKind(str, Enum):
    STR = "str"
    INT = "int"
    BOOL = "bool"


# 没有默认值的必填字段哨兵
REQUIRED: Any = object()

VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
MIN_PORT = 1
MAX_PORT = 65535


@dataclass(frozen=True)
class FieldSpec:
    """单个配置字段的声明。"""

    key: str                      # 点分层级键，如 "app.log_level"
    kind: ConfigKind              # 值类型
    env: str                      # 对应的环境变量名
    default: Any = REQUIRED       # 默认值；REQUIRED 表示必填
    choices: tuple[Any, ...] | None = None
    ge: int | None = None         # 数值下界（含）
    le: int | None = None         # 数值上界（含）
    help: str = ""


@dataclass(frozen=True)
class AppConfig:
    """应用最终生效的强类型配置。"""

    app_name: str
    environment: str
    debug: bool
    log_level: str
    api_prefix: str
    host: str
    port: int


FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        key="app.name",
        kind=ConfigKind.STR,
        env="APP_NAME",
        default="fastapi-app-scaffold",
        help="应用名称",
    ),
    FieldSpec(
        key="app.environment",
        kind=ConfigKind.STR,
        env="APP_ENVIRONMENT",
        default="development",
        help="运行环境，如 development/staging/production",
    ),
    FieldSpec(
        key="app.debug",
        kind=ConfigKind.BOOL,
        env="APP_DEBUG",
        default=False,
        help="是否开启调试模式",
    ),
    FieldSpec(
        key="app.log_level",
        kind=ConfigKind.STR,
        env="APP_LOG_LEVEL",
        default="INFO",
        choices=VALID_LOG_LEVELS,
        help="日志级别（大小写不敏感）",
    ),
    FieldSpec(
        key="api.prefix",
        kind=ConfigKind.STR,
        env="API_PREFIX",
        default="/api",
        help="业务 API 统一挂载前缀，必须以 / 开头",
    ),
    FieldSpec(
        key="server.host",
        kind=ConfigKind.STR,
        env="SERVER_HOST",
        default="127.0.0.1",
        help="监听地址",
    ),
    FieldSpec(
        key="server.port",
        kind=ConfigKind.INT,
        env="SERVER_PORT",
        default=8000,
        ge=MIN_PORT,
        le=MAX_PORT,
        help="监听端口 1-65535",
    ),
)

FIELD_BY_KEY: dict[str, FieldSpec] = {f.key: f for f in FIELDS}
FIELD_BY_ENV: dict[str, FieldSpec] = {f.env: f for f in FIELDS}

# 配置文件中的废弃键 -> 新键
DEPRECATED_FILE_KEYS: dict[str, str] = {
    "debug": "app.debug",
    "name": "app.name",
    "log_level": "app.log_level",
}

# 废弃环境变量 -> 新环境变量
DEPRECATED_ENVS: dict[str, str] = {
    "DEBUG": "APP_DEBUG",
    "APP_PORT": "SERVER_PORT",
}
