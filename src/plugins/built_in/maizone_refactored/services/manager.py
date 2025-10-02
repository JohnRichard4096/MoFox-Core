"""
服务管理器/定位器
这是一个独立的模块，用于注册和获取插件内的全局服务实例，以避免循环导入。
"""

from collections.abc import Callable
from typing import Any

from .qzone_service import QZoneService

# --- 全局服务注册表 ---
_services: dict[str, Any] = {}


def register_service(name: str, instance: Any):
    """将一个服务实例注册到全局注册表。"""
    _services[name] = instance


def get_qzone_service() -> QZoneService:
    """全局可用的QZone服务获取函数"""
    return _services["qzone"]


def get_config_getter() -> Callable:
    """全局可用的配置获取函数"""
    return _services["get_config"]
