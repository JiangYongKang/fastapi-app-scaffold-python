"""配置加载阶段的错误分类。

每一类错误对应一种可区分的启动失败原因，避免调用方只能拿到模糊的报错。
"""

from __future__ import annotations


class ConfigError(Exception):
    """所有配置错误的基类。"""


class MissingConfigError(ConfigError):
    """必填字段缺失（没有任何一层提供该值）。"""


class ConfigTypeError(ConfigError):
    """值的类型无法转换为字段声明的类型。"""


class ConfigValidationError(ConfigError):
    """类型正确但取值非法（超出允许范围/不在枚举内）。"""


class DeprecatedConfigError(ConfigError):
    """使用了已废弃的旧配置项。"""


class UnknownConfigKeyError(ConfigError):
    """出现了 schema 未定义的配置键（通常是拼写错误）。"""
