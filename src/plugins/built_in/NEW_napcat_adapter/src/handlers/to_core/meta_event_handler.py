"""元事件处理器"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

from src.common.logger import get_logger

if TYPE_CHECKING:
    from ...plugin import NapcatAdapter

logger = get_logger("napcat_adapter.meta_event_handler")


class MetaEventHandler:
    """处理 Napcat 元事件（心跳、生命周期）"""

    def __init__(self, adapter: "NapcatAdapter"):
        self.adapter = adapter
        self.plugin_config: Optional[Dict[str, Any]] = None

    def set_plugin_config(self, config: Dict[str, Any]) -> None:
        """设置插件配置"""
        self.plugin_config = config

    async def handle_meta_event(self, raw: Dict[str, Any]):
        """处理元事件"""
        # 简化版本：返回一个空的 MessageEnvelope
        pass
