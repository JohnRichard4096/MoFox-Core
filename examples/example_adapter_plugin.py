"""
示例：演示如何创建一个完整的适配器插件

这个示例展示了：
1. 如何继承 BaseAdapter 创建自定义适配器
2. 如何在插件中集成适配器
3. 如何支持子进程运行
"""

from pathlib import Path
from typing import Any, Dict, Optional

from mofox_bus import CoreMessageSink, InProcessCoreSink, MessageEnvelope, WebSocketAdapterOptions

from src.plugin_system.base import BaseAdapter, BasePlugin, PluginMetadata, AdapterInfo
from src.plugin_system import register_plugin

class ExampleAdapter(BaseAdapter):
    """示例适配器"""

    adapter_name = "example_adapter"
    adapter_version = "1.0.0"
    adapter_author = "MoFox Team"
    adapter_description = "示例适配器，演示如何创建适配器插件"
    platform = "example"
    
    # 是否在子进程中运行（设为 False 在主进程中运行）
    run_in_subprocess = False
    
    # 子进程入口脚本（如果 run_in_subprocess=True）
    subprocess_entry = "adapter_entry.py"

    def __init__(self, core_sink: CoreMessageSink, plugin: Optional[BasePlugin] = None):
        """初始化适配器"""
        # 配置 WebSocket 传输（如果需要）
        transport = None
        if plugin and plugin.config:
            ws_url = plugin.config.get("websocket_url")
            if ws_url:
                transport = WebSocketAdapterOptions(
                    url=ws_url,
                    headers={"platform": self.platform},
                )
        
        super().__init__(core_sink, plugin=plugin, transport=transport)

    def from_platform_message(self, raw: Dict[str, Any]) -> MessageEnvelope:
        """
        将平台消息转换为 MessageEnvelope
        
        Args:
            raw: 平台原始消息
            
        Returns:
            MessageEnvelope: 统一消息信封
        """
        # 示例：假设平台消息格式为
        # {
        #     "id": "msg_123",
        #     "user_id": "user_456",
        #     "group_id": "group_789",
        #     "text": "Hello",
        #     "timestamp": 1234567890
        # }
        
        envelope: MessageEnvelope = {
            "id": raw.get("id", "unknown"),
            "direction": "incoming",
            "platform": self.platform,
            "timestamp_ms": int(raw.get("timestamp", 0) * 1000),
            "channel": {
                "channel_id": raw.get("group_id", raw.get("user_id", "unknown")),
                "channel_type": "group" if "group_id" in raw else "private",
            },
            "sender": {
                "user_id": raw.get("user_id", "unknown"),
                "role": "user",
            },
            "content": {
                "type": "text",
                "text": raw.get("text", ""),
            },
            "conversation_id": raw.get("group_id", raw.get("user_id", "unknown")),
        }
        
        return envelope

    async def _send_platform_message(self, envelope: MessageEnvelope) -> None:
        """
        发送消息到平台
        
        如果配置了 WebSocketAdapterOptions，会自动通过 WebSocket 发送。
        否则需要在这里实现自定义发送逻辑。
        """
        if self._transport_config:
            # 使用自动传输
            await super()._send_platform_message(envelope)
        else:
            # 自定义发送逻辑
            # 例如：调用平台 API
            pass


class ExampleAdapterPlugin(BasePlugin):
    """示例适配器插件"""

    plugin_name = "example_adapter_plugin"
    enable_plugin = True  # 设为 False 禁用插件
    plugin_version = "1.0.0"
    plugin_author = "MoFox Team"

    def get_plugin_components(self) -> list:
        """获取插件组件列表
        
        适配器作为组件返回，插件管理器会自动创建实例并传入 core_sink
        """
        return [
            # 适配器组件 - 使用 get_adapter_info() 方法
            (ExampleAdapter.get_adapter_info(), ExampleAdapter),
        ]


# 注册插件
def register_plugin() -> type[BasePlugin]:
    """插件注册函数"""
    return ExampleAdapterPlugin
