"""资源生命周期相关错误，原因彼此可区分。"""

from __future__ import annotations


class ResourceError(Exception):
    """所有资源错误的基类。"""


class ResourceNotFoundError(ResourceError):
    """请求了一个未在管理器登记的资源（通常是装配遗漏）。"""


class ResourceAlreadyRegisteredError(ResourceError):
    """同名资源被重复登记。"""


class ResourceNotReadyError(ResourceError):
    """资源尚未初始化完成（或正在启动），请求必须被拒绝。"""


class ResourceReleasedError(ResourceError):
    """资源已经随应用关闭而释放，请求必须被拒绝。"""
