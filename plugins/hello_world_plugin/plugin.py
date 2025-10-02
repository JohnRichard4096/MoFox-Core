import logging
import random
from typing import Any

from src.plugin_system import (
    ActionActivationType,
    BaseAction,
    BaseEventHandler,
    BasePlugin,
    BaseTool,
    ChatType,
    CommandArgs,
    ComponentInfo,
    ConfigField,
    EventType,
    PlusCommand,
    register_plugin,
)
from src.plugin_system.base.base_event import HandlerResult


class StartupMessageHandler(BaseEventHandler):
    """启动时打印消息的事件处理器。"""

    handler_name = "hello_world_startup_handler"
    handler_description = "在机器人启动时打印一条日志。"
    init_subscribe = [EventType.ON_START]

    async def execute(self, params: dict) -> HandlerResult:
        logging.info("🎉 Hello World 插件已启动，准备就绪！")
        return HandlerResult(success=True, continue_process=True)


class GetSystemInfoTool(BaseTool):
    """一个提供系统信息的示例工具。"""

    name = "get_system_info"
    description = "获取当前系统的模拟版本和状态信息。"
    available_for_llm = True
    parameters = []

    async def execute(self, function_args: dict[str, Any]) -> dict[str, Any]:
        return {"name": self.name, "content": "系统版本: 1.0.1, 状态: 运行正常"}


class HelloCommand(PlusCommand):
    """一个简单的 /hello 命令，使用配置文件中的问候语。"""

    command_name = "hello"
    command_description = "向机器人发送一个简单的问候。"
    command_aliases = ["hi", "你好"]
    chat_type_allow = ChatType.ALL

    async def execute(self, args: CommandArgs) -> tuple[bool, str | None, bool]:
        greeting = str(self.get_config("greeting.message", "Hello, World! 我是一个由 MoFox_Bot 驱动的插件。"))
        await self.send_text(greeting)
        return True, "成功发送问候", True


class RandomEmojiAction(BaseAction):
    """一个随机发送表情的动作。"""

    action_name = "random_emoji"
    action_description = "随机发送一个表情符号，增加聊天的趣味性。"
    activation_type = ActionActivationType.RANDOM
    random_activation_probability = 0.1
    action_require = ["当对话气氛轻松时", "可以用来回应简单的情感表达"]
    associated_types = ["text"]

    async def execute(self) -> tuple[bool, str]:
        emojis = ["😊", "😂", "👍", "🎉", "🤔", "🤖"]
        await self.send_text(random.choice(emojis))
        return True, "成功发送了一个随机表情"


@register_plugin
class HelloWorldPlugin(BasePlugin):
    """一个包含四大核心组件和高级配置功能的入门示例插件。"""

    plugin_name = "hello_world_plugin"
    enable_plugin = True
    dependencies = []
    python_dependencies = []
    config_file_name = "config.toml"
    enable_plugin = False

    config_schema = {
        "meta": {
            "config_version": ConfigField(type=int, default=1, description="配置文件版本，请勿手动修改。"),
        },
        "greeting": {
            "message": ConfigField(
                type=str, default="这是来自配置文件的问候！👋", description="HelloCommand 使用的问候语。"
            ),
        },
        "components": {
            "hello_command_enabled": ConfigField(type=bool, default=True, description="是否启用 /hello 命令。"),
            "random_emoji_action_enabled": ConfigField(type=bool, default=True, description="是否启用随机表情动作。"),
        },
    }

    def get_plugin_components(self) -> list[tuple[ComponentInfo, type]]:
        """根据配置文件动态注册插件的功能组件。"""
        components: list[tuple[ComponentInfo, type]] = []

        components.append((StartupMessageHandler.get_handler_info(), StartupMessageHandler))
        components.append((GetSystemInfoTool.get_tool_info(), GetSystemInfoTool))

        if self.get_config("components.hello_command_enabled", True):
            components.append((HelloCommand.get_command_info(), HelloCommand))

        if self.get_config("components.random_emoji_action_enabled", True):
            components.append((RandomEmojiAction.get_action_info(), RandomEmojiAction))

        return components
