"""资源生命周期相关错误。"""

from __future__ import annotations


class ResourceError(Exception):
    """所有资源错误的基类。"""


class ResourceNotReadyError(ResourceError):
    """资源尚未初始化完成，请求被拒绝。"""


class ResourceReleasedError(ResourceError):
    """资源已经释放，请求被拒绝。"""


class ResourceNotFoundError(ResourceError):
    """请求了一个未登记的资源。"""


class ResourceAlreadyRegisteredError(ResourceError):
    """同名资源重复登记。"""
