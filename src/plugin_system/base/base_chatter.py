from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

from src.common.data_models.message_manager_data_model import StreamContext
from src.plugin_system.base.component_types import ChatterInfo, ComponentType

from .component_types import ChatType

if TYPE_CHECKING:
    from src.chat.planner_actions.action_manager import ChatterActionManager


class BaseChatter(ABC):
    chatter_name: str = ""
    """Chatter组件名称"""
    chatter_description: str = ""
    """Chatter组件描述"""
    chat_types: ClassVar[list[ChatType]] = [ChatType.PRIVATE, ChatType.GROUP]

    def __init__(self, stream_id: str, action_manager: "ChatterActionManager", plugin_config: dict | None = None):
        """
        初始化聊天处理器

        Args:
            stream_id: 聊天流ID
            action_manager: 动作管理器
            plugin_config: 插件配置字典
        """
        self.stream_id = stream_id
        self.action_manager = action_manager
        if plugin_config is None:
            plugin_config = getattr(self.__class__, "plugin_config", {})

        self.plugin_config = plugin_config or {}

    @abstractmethod
    async def execute(self, context: StreamContext) -> dict:
        """
        执行聊天处理逻辑

        Args:
            context: StreamContext对象，包含聊天上下文信息

        Returns:
            处理结果字典
        """
        pass

    @classmethod
    def get_chatter_info(cls) -> "ChatterInfo":
        """构造并返回ChatterInfo
        Returns:
            ChatterInfo实例
        """

        return ChatterInfo(
            name=cls.chatter_name,
            description=cls.chatter_description or "No description provided.",
            chat_type_allow=cls.chat_types[0],
            component_type=ComponentType.CHATTER,
        )

    def get_config(self, key: str, default=None):
        """获取插件配置，支持嵌套键"""
        if not self.plugin_config:
            return default

        current = self.plugin_config
        for part in key.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default
        return current
