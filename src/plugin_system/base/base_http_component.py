from abc import ABC, abstractmethod

from fastapi import APIRouter

from .component_types import ComponentType, RouterInfo


class BaseRouterComponent(ABC):
    """
    对外暴露HTTP接口的基类。
    插件路由类应继承本类，并实现 register_endpoints 方法注册API路由。
    """

    # 基本元数据，可由插件类读取
    component_name: str
    component_description: str
    component_version: str = "1.0.0"

    # 每个路由实例都拥有自己的 APIRouter
    router: APIRouter

    def __init__(self, plugin_config: dict | None = None):
        if plugin_config is None:
            plugin_config = getattr(self.__class__, "plugin_config", {})
        self.plugin_config = plugin_config or {}

        self.router = APIRouter()
        self.register_endpoints()

    @abstractmethod
    def register_endpoints(self) -> None:
        """
        子类需要实现的方法。
        在此方法中定义插件的HTTP接口。
        """
        pass

    @classmethod
    def get_router_info(cls) -> "RouterInfo":
        """构造 RouterInfo"""
        return RouterInfo(
            name=cls.component_name,
            description=getattr(cls, "component_description", "路由组件"),
            component_type=ComponentType.ROUTER,
        )

    def get_config(self, key: str, default=None):
        """获取插件配置值，支持嵌套键"""
        if not self.plugin_config:
            return default

        current = self.plugin_config
        for part in key.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default
        return current
