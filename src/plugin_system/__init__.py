"""
MaiBot 插件系统

提供统一的插件开发和管理框架
"""

# 导出主要的公共接口
from .apis import (
    chat_api,
    component_manage_api,
    config_api,
    database_api,
    emoji_api,
    generator_api,
    get_logger,
    llm_api,
    message_api,
    person_api,
    plugin_manage_api,
    register_plugin,
    send_api,
    tool_api,
)
from .base import (
    ActionActivationType,
    ActionInfo,
    BaseAction,
    BaseCommand,
    BaseEventHandler,
    BasePlugin,
    BaseTool,
    ChatMode,
    ChatType,
    CommandArgs,
    CommandInfo,
    ComponentInfo,
    ComponentType,
    ConfigField,
    EventHandlerInfo,
    EventType,
    MaiMessages,
    PluginInfo,
    # 新增的增强命令系统
    PlusCommand,
    PlusCommandAdapter,
    PlusCommandInfo,
    PythonDependency,
    ToolInfo,
    ToolParamType,
    create_plus_command_adapter,
)

# 导入工具模块
from .utils import (
    ManifestValidator,
    # ManifestGenerator,
    # validate_plugin_manifest,
    # generate_plugin_manifest,
)
from .utils.dependency_config import configure_dependency_settings, get_dependency_config

# 导入依赖管理模块
from .utils.dependency_manager import configure_dependency_manager, get_dependency_manager

__version__ = "2.0.0"

__all__ = [
    # API 模块
    "chat_api",
    "tool_api",
    "component_manage_api",
    "config_api",
    "database_api",
    "emoji_api",
    "generator_api",
    "llm_api",
    "message_api",
    "person_api",
    "plugin_manage_api",
    "send_api",
    "register_plugin",
    "get_logger",
    # 基础类
    "BasePlugin",
    "BaseAction",
    "BaseCommand",
    "BaseTool",
    "BaseEventHandler",
    # 增强命令系统
    "PlusCommand",
    "CommandArgs",
    "PlusCommandAdapter",
    "create_plus_command_adapter",
    "create_plus_command_adapter",
    # 类型定义
    "ComponentType",
    "ActionActivationType",
    "ChatMode",
    "ChatType",
    "ComponentInfo",
    "ActionInfo",
    "CommandInfo",
    "PluginInfo",
    "ToolInfo",
    "PythonDependency",
    "EventHandlerInfo",
    "EventType",
    "ToolParamType",
    # 消息
    "MaiMessages",
    # 装饰器
    "register_plugin",
    "ConfigField",
    # 工具函数
    "ManifestValidator",
    "get_logger",
    # 依赖管理
    "get_dependency_manager",
    "configure_dependency_manager",
    "get_dependency_config",
    "configure_dependency_settings",
    # "ManifestGenerator",
    # "validate_plugin_manifest",
    # "generate_plugin_manifest",
]
