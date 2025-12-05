from __future__ import annotations

# --- 标准库导入 ---
from pathlib import Path
from re import Pattern
from typing import Any, cast

# --- 第三方库导入 ---
import toml

# --- 项目内模块导入 ---
from src.common.logger import get_logger
from src.config.config import global_config as bot_config
from src.plugin_system.base.base_action import BaseAction
from src.plugin_system.base.base_adapter import BaseAdapter
from src.plugin_system.base.base_chatter import BaseChatter
from src.plugin_system.base.base_command import BaseCommand
from src.plugin_system.base.base_events_handler import BaseEventHandler
from src.plugin_system.base.base_http_component import BaseRouterComponent
from src.plugin_system.base.base_interest_calculator import BaseInterestCalculator
from src.plugin_system.base.base_prompt import BasePrompt
from src.plugin_system.base.base_tool import BaseTool
from src.plugin_system.base.component_types import (
    ActionInfo,
    AdapterInfo,
    ChatterInfo,
    CommandInfo,
    ComponentInfo,
    ComponentType,
    EventHandlerInfo,
    InterestCalculatorInfo,
    PluginInfo,
    PlusCommandInfo,
    PromptInfo,
    ToolInfo,
)
from src.plugin_system.base.plus_command import PlusCommand, create_legacy_command_adapter

# --- 日志记录器 ---
logger = get_logger("component_registry")

# --- 类型别名 ---
# 统一的组件类类型别名，方便类型提示，涵盖所有支持的组件基类
ComponentClassType = (
    type[BaseCommand]
    | type[BaseAction]
    | type[BaseTool]
    | type[BaseEventHandler]
    | type[PlusCommand]
    | type[BaseChatter]
    | type[BaseInterestCalculator]
    | type[BasePrompt]
    | type[BaseRouterComponent]
    | type[BaseAdapter]
)


def _assign_plugin_attrs(cls: Any, plugin_name: str, plugin_config: dict) -> None:
    """
    为组件类动态赋予插件相关属性。

    这是一个辅助函数，用于避免在各个注册函数中重复编写相同的属性设置代码。

    Args:
        cls: 需要设置属性的组件类
        plugin_name: 插件的名称
        plugin_config: 插件的配置信息字典
    """
    cls.plugin_name = plugin_name
    cls.plugin_config = plugin_config


class ComponentRegistry:
    """
    统一的组件注册中心。

    该类是插件系统的核心，负责管理所有插件组件的注册、发现、状态管理和生命周期。
    它为不同类型的组件（如 Command, Action, Tool 等）提供了统一的注册接口和专门的查询方法。

    主要职责:
        - 注册和取消注册插件与组件
        - 按类型和名称存储和索引所有组件
        - 管理组件的全局启用/禁用状态
        - 支持会话级别的组件局部（临时）启用/禁用状态
        - 提供按类型、名称或状态查询组件的方法
        - 动态加载和管理 MCP (Model-Copilot-Plugin) 工具

    Attributes:
        _components: 核心注册表，使用命名空间键 f"{component_type}.{component_name}"
        _components_by_type: 按类型分类的组件注册表
        _components_classes: 存储组件类本身，用于实例化
        _plugins: 插件注册表
        _local_component_states: 局部组件状态管理器，用于会话级别的临时状态覆盖
    """

    # =================================================================
    # == 初始化 (Initialization)
    # =================================================================

    def __init__(self):
        """
        初始化组件注册中心，创建所有必要的注册表。

        注册表分为以下几类:
            1. 通用注册表: 存储所有组件的通用信息
            2. 插件注册表: 存储插件元信息
            3. 特定类型注册表: 为每种组件类型提供专用的快速查询
            4. 状态管理: 支持全局和局部（会话级）状态控制
        """
        # --- 通用注册表 ---
        # 核心注册表，使用命名空间键 f"{component_type}.{component_name}"
        self._components: dict[str, ComponentInfo] = {}
        # 按类型分类的组件注册表，方便按类型快速查找
        self._components_by_type: dict[ComponentType, dict[str, ComponentInfo]] = {
            t: {} for t in ComponentType
        }
        # 存储组件类本身，用于实例化
        self._components_classes: dict[str, ComponentClassType] = {}

        # --- 插件注册表 ---
        self._plugins: dict[str, PluginInfo] = {}  # 插件名 -> 插件信息

        # --- 特定类型组件的专用注册表 ---
        # Action 相关
        self._action_registry: dict[str, type[BaseAction]] = {}  # Action名 -> Action类
        self._default_actions: dict[str, ActionInfo] = {}  # 存储全局启用的Action

        # Command 相关 (旧版，用于兼容)
        self._command_registry: dict[str, type[BaseCommand]] = {}  # Command名 -> Command类
        self._command_patterns: dict[Pattern, str] = {}  # 编译后的正则表达式 -> Command名

        # PlusCommand 相关 (新版命令系统)
        self._plus_command_registry: dict[str, type[PlusCommand]] = {}  # PlusCommand名 -> 类

        # Tool 相关
        self._tool_registry: dict[str, type[BaseTool]] = {}  # Tool名 -> Tool类
        self._llm_available_tools: dict[str, type[BaseTool]] = {}  # 存储全局启用的Tool

        # EventHandler 相关
        self._event_handler_registry: dict[str, type[BaseEventHandler]] = {}
        self._enabled_event_handlers: dict[str, type[BaseEventHandler]] = {}

        # Chatter 相关
        self._chatter_registry: dict[str, type[BaseChatter]] = {}
        self._enabled_chatter_registry: dict[str, type[BaseChatter]] = {}

        # InterestCalculator 相关
        self._interest_calculator_registry: dict[str, type[BaseInterestCalculator]] = {}
        self._enabled_interest_calculator_registry: dict[str, type[BaseInterestCalculator]] = {}

        # Prompt 相关
        self._prompt_registry: dict[str, type[BasePrompt]] = {}
        self._enabled_prompt_registry: dict[str, type[BasePrompt]] = {}

        # Adapter 相关
        self._adapter_registry: dict[str, type[BaseAdapter]] = {}
        self._enabled_adapter_registry: dict[str, type[BaseAdapter]] = {}

        # --- MCP 工具 ---
        self._mcp_tools: list[Any] = []  # 存储 MCP 工具适配器实例
        self._mcp_tools_loaded = False  # 标记 MCP 工具是否已加载

        # --- 状态管理器 ---
        # 延迟导入以避免循环依赖
        from src.plugin_system.core.component_state_manager import ComponentStateManager
        self._state_manager = ComponentStateManager(self)

        logger.info("组件注册中心初始化完成")

    # =================================================================
    # == 插件注册 (Plugin Registration)
    # =================================================================

    def register_plugin(self, plugin_info: PluginInfo) -> bool:
        """
        注册一个插件。

        Args:
            plugin_info: 包含插件元数据的信息对象

        Returns:
            如果插件是新的并成功注册返回 True；如果插件已存在返回 False
        """
        plugin_name = plugin_info.name
        if plugin_name in self._plugins:
            logger.warning(f"插件 {plugin_name} 已存在，跳过注册")
            return False
        self._plugins[plugin_name] = plugin_info
        logger.debug(f"已注册插件: {plugin_name} (组件数量: {len(plugin_info.components)})")
        return True

    async def unregister_plugin(self, plugin_name: str) -> bool:
        """
        卸载一个插件及其所有关联的组件。

        这是一个高级操作，会依次移除插件的所有组件，然后移除插件本身的注册信息。

        Args:
            plugin_name: 要卸载的插件的名称

        Returns:
            如果所有组件和插件本身都成功卸载返回 True；否则返回 False
        """
        plugin_info = self.get_plugin_info(plugin_name)
        if not plugin_info:
            logger.warning(f"插件 {plugin_name} 未注册，无法卸载")
            return False

        logger.info(f"开始卸载插件: {plugin_name}")
        failed_components = []

        # 逐个移除插件的所有组件
        for component_info in plugin_info.components:
            try:
                success = await self.remove_component(
                    component_info.name, component_info.component_type, plugin_name
                )
                if not success:
                    failed_components.append(f"{component_info.component_type}.{component_info.name}")
            except Exception as e:
                logger.error(f"移除组件 {component_info.name} 时发生异常: {e}")
                failed_components.append(f"{component_info.component_type}.{component_info.name}")

        # 移除插件注册信息
        self._plugins.pop(plugin_name, None)

        if failed_components:
            logger.warning(f"插件 {plugin_name} 部分组件卸载失败: {failed_components}")
            return False

        logger.info(f"插件 {plugin_name} 卸载成功")
        return True

    # =================================================================
    # == 组件注册 (Component Registration)
    # =================================================================

    def register_component(
        self, component_info: ComponentInfo, component_class: ComponentClassType
    ) -> bool:
        """
        注册一个组件。

        这是所有组件注册的统一入口点。它会验证组件信息，然后根据组件类型
        分发到特定的内部注册方法。

        Args:
            component_info: 组件的元数据信息
            component_class: 组件的类定义

        Returns:
            注册成功返回 True，否则返回 False
        """
        component_name = component_info.name
        component_type = component_info.component_type
        plugin_name = getattr(component_info, "plugin_name", "unknown")

        # --- 名称合法性检查 ---
        # 组件名和插件名不能包含 '.'，因为它用于命名空间分隔
        if "." in component_name or "." in plugin_name:
            logger.error("组件名称或插件名称包含非法字符 '.'")
            return False

        # --- 冲突检查 ---
        namespaced_name = f"{component_type.value}.{component_name}"
        if namespaced_name in self._components:
            existing_plugin = getattr(self._components[namespaced_name], "plugin_name", "unknown")
            logger.warning(
                f"组件名冲突: '{component_name}' 已被插件 '{existing_plugin}' 注册"
            )
            return False

        # --- 通用注册 ---
        self._components[namespaced_name] = component_info
        self._components_by_type[component_type][component_name] = component_info
        self._components_classes[namespaced_name] = component_class

        # --- 按类型分发到特定注册方法 ---
        handlers = {
            ComponentType.ACTION: self._register_action,
            ComponentType.COMMAND: self._register_command,
            ComponentType.PLUS_COMMAND: self._register_plus_command,
            ComponentType.TOOL: self._register_tool,
            ComponentType.EVENT_HANDLER: self._register_event_handler,
            ComponentType.CHATTER: self._register_chatter,
            ComponentType.INTEREST_CALCULATOR: self._register_interest_calculator,
            ComponentType.PROMPT: self._register_prompt,
            ComponentType.ROUTER: self._register_router,
            ComponentType.ADAPTER: self._register_adapter,
        }

        handler = handlers.get(component_type)
        if not handler:
            logger.warning(f"未知组件类型: {component_type}")
            return False

        if not handler(component_info, component_class):
            return False

        logger.debug(f"已注册{component_type}组件: '{component_name}' [插件: {plugin_name}]")
        return True

    async def remove_component(
        self, component_name: str, component_type: ComponentType, plugin_name: str
    ) -> bool:
        """
        从注册中心移除一个指定的组件。

        Args:
            component_name: 要移除的组件的名称
            component_type: 组件的类型
            plugin_name: 组件所属的插件名称 (用于日志记录)

        Returns:
            移除成功返回 True，否则返回 False
        """
        if not self.get_component_class(component_name, component_type):
            logger.warning(f"组件 {component_name} ({component_type.value}) 未注册")
            return False

        try:
            # --- 特定类型的清理操作 ---
            match component_type:
                case ComponentType.ACTION:
                    self._action_registry.pop(component_name, None)
                    self._default_actions.pop(component_name, None)
                case ComponentType.COMMAND:
                    self._command_registry.pop(component_name, None)
                    # 移除所有关联的命令模式
                    self._command_patterns = {
                        k: v for k, v in self._command_patterns.items() if v != component_name
                    }
                case ComponentType.PLUS_COMMAND:
                    self._plus_command_registry.pop(component_name, None)
                case ComponentType.TOOL:
                    self._tool_registry.pop(component_name, None)
                    self._llm_available_tools.pop(component_name, None)
                case ComponentType.EVENT_HANDLER:
                    self._event_handler_registry.pop(component_name, None)
                    self._enabled_event_handlers.pop(component_name, None)
                    # 从事件管理器中移除
                    from .event_manager import event_manager
                    event_manager.remove_event_handler(component_name)
                case ComponentType.CHATTER:
                    self._chatter_registry.pop(component_name, None)
                    self._enabled_chatter_registry.pop(component_name, None)
                case ComponentType.INTEREST_CALCULATOR:
                    self._interest_calculator_registry.pop(component_name, None)
                    self._enabled_interest_calculator_registry.pop(component_name, None)
                case ComponentType.PROMPT:
                    self._prompt_registry.pop(component_name, None)
                    self._enabled_prompt_registry.pop(component_name, None)
                case ComponentType.ADAPTER:
                    self._adapter_registry.pop(component_name, None)
                    self._enabled_adapter_registry.pop(component_name, None)
                case ComponentType.ROUTER:
                    # Router 的 HTTP 端点无法在运行时动态移除
                    logger.warning("Router组件无法在运行时动态移除，将在下次重启后生效")

            # --- 通用注册信息清理 ---
            namespaced_name = f"{component_type.value}.{component_name}"
            self._components.pop(namespaced_name, None)
            self._components_by_type[component_type].pop(component_name, None)
            self._components_classes.pop(namespaced_name, None)

            logger.info(f"组件 {component_name} ({component_type.value}) 已移除")
            return True
        except Exception as e:
            logger.error(f"移除组件时发生错误: {e}", exc_info=True)
            return False

    # =================================================================
    # == 内部注册方法 (Internal Registration Methods)
    # =================================================================

    def _register_action(self, info: ComponentInfo, cls: ComponentClassType) -> bool:
        """
        注册 Action 组件到 Action 特定注册表。

        Args:
            info: Action 组件的元数据信息
            cls: Action 组件的类定义

        Returns:
            注册成功返回 True
        """
        action_info = cast(ActionInfo, info)
        action_class = cast(type[BaseAction], cls)
        _assign_plugin_attrs(action_class, info.plugin_name, self.get_plugin_config(info.plugin_name) or {})
        self._action_registry[info.name] = action_class
        # 如果组件默认启用，则添加到默认动作集
        if action_info.enabled:
            self._default_actions[info.name] = action_info
        return True

    def _register_command(self, info: ComponentInfo, cls: ComponentClassType) -> bool:
        """
        通过适配器将旧版 Command 注册为 PlusCommand。

        旧版 Command 会自动转换为 PlusCommand 以保持向后兼容性。

        Args:
            info: Command 组件的元数据信息
            cls: Command 组件的类定义

        Returns:
            注册成功返回 True
        """
        command_class = cast(type[BaseCommand], cls)
        logger.warning(
            f"检测到旧版Command组件 '{info.name}'，建议迁移到PlusCommand"
        )
        # 使用适配器将其转换为 PlusCommand
        adapted_class = create_legacy_command_adapter(command_class)
        plus_info = adapted_class.get_plus_command_info()
        plus_info.plugin_name = info.plugin_name  # 继承插件名
        return self._register_plus_command(plus_info, adapted_class)

    def _register_plus_command(self, info: ComponentInfo, cls: ComponentClassType) -> bool:
        """
        注册 PlusCommand 组件到特定注册表。

        Args:
            info: PlusCommand 组件的元数据信息
            cls: PlusCommand 组件的类定义

        Returns:
            注册成功返回 True
        """
        plus_class = cast(type[PlusCommand], cls)
        _assign_plugin_attrs(plus_class, info.plugin_name, self.get_plugin_config(info.plugin_name) or {})
        self._plus_command_registry[info.name] = plus_class
        return True

    def _register_tool(self, info: ComponentInfo, cls: ComponentClassType) -> bool:
        """
        注册 Tool 组件到 Tool 特定注册表。

        Args:
            info: Tool 组件的元数据信息
            cls: Tool 组件的类定义

        Returns:
            注册成功返回 True
        """
        tool_info = cast(ToolInfo, info)
        tool_class = cast(type[BaseTool], cls)
        _assign_plugin_attrs(tool_class, info.plugin_name, self.get_plugin_config(info.plugin_name) or {})
        self._tool_registry[info.name] = tool_class
        # 如果组件默认启用，则添加到 LLM 可用工具集
        if tool_info.enabled:
            self._llm_available_tools[info.name] = tool_class
        return True

    def _register_event_handler(self, info: ComponentInfo, cls: ComponentClassType) -> bool:
        """
        注册 EventHandler 组件并订阅事件。

        Args:
            info: EventHandler 组件的元数据信息
            cls: EventHandler 组件的类定义

        Returns:
            注册成功返回 True，注册到事件管理器失败返回 False
        """
        handler_info = cast(EventHandlerInfo, info)
        handler_class = cast(type[BaseEventHandler], cls)
        plugin_config = self.get_plugin_config(info.plugin_name) or {}
        _assign_plugin_attrs(handler_class, info.plugin_name, plugin_config)
        self._event_handler_registry[info.name] = handler_class

        # 如果组件未启用，仅注册信息，不订阅事件
        if not handler_info.enabled:
            logger.warning(f"EventHandler组件 {info.name} 未启用")
            return True

        # 延迟导入以避免循环依赖
        from src.plugin_system.core.event_manager import event_manager
        return event_manager.register_event_handler(handler_class, plugin_config)

    def _register_chatter(self, info: ComponentInfo, cls: ComponentClassType) -> bool:
        """
        注册 Chatter 组件到 Chatter 特定注册表。

        Args:
            info: Chatter 组件的元数据信息
            cls: Chatter 组件的类定义

        Returns:
            注册成功返回 True
        """
        chatter_info = cast(ChatterInfo, info)
        chatter_class = cast(type[BaseChatter], cls)
        _assign_plugin_attrs(chatter_class, info.plugin_name, self.get_plugin_config(info.plugin_name) or {})
        self._chatter_registry[info.name] = chatter_class
        if chatter_info.enabled:
            self._enabled_chatter_registry[info.name] = chatter_class
        return True

    def _register_interest_calculator(self, info: ComponentInfo, cls: ComponentClassType) -> bool:
        """
        注册 InterestCalculator 组件到特定注册表。

        Args:
            info: InterestCalculator 组件的元数据信息
            cls: InterestCalculator 组件的类定义

        Returns:
            注册成功返回 True
        """
        calc_info = cast(InterestCalculatorInfo, info)
        calc_class = cast(type[BaseInterestCalculator], cls)
        _assign_plugin_attrs(calc_class, info.plugin_name, self.get_plugin_config(info.plugin_name) or {})
        self._interest_calculator_registry[info.name] = calc_class
        if calc_info.enabled:
            self._enabled_interest_calculator_registry[info.name] = calc_class
        return True

    def _register_prompt(self, info: ComponentInfo, cls: ComponentClassType) -> bool:
        """
        注册 Prompt 组件到 Prompt 特定注册表。

        Args:
            info: Prompt 组件的元数据信息
            cls: Prompt 组件的类定义

        Returns:
            注册成功返回 True
        """
        prompt_info = cast(PromptInfo, info)
        prompt_class = cast(type[BasePrompt], cls)
        _assign_plugin_attrs(prompt_class, info.plugin_name, self.get_plugin_config(info.plugin_name) or {})
        self._prompt_registry[info.name] = prompt_class
        if prompt_info.enabled:
            self._enabled_prompt_registry[info.name] = prompt_class
        return True

    def _register_router(self, info: ComponentInfo, cls: ComponentClassType) -> bool:
        """
        注册 Router 组件并将其 HTTP 端点挂载到主 FastAPI 应用。

        Args:
            info: Router 组件的元数据信息
            cls: Router 组件的类定义

        Returns:
            注册成功返回 True，出错返回 False
        """
        # 检查总开关是否开启
        assert bot_config
        if not bot_config.plugin_http_system.enable_plugin_http_endpoints:
            logger.info("插件HTTP端点功能已禁用，跳过路由注册")
            return True

        try:
            from src.common.server import get_global_server
            router_class = cast(type[BaseRouterComponent], cls)
            _assign_plugin_attrs(router_class, info.plugin_name, self.get_plugin_config(info.plugin_name) or {})

            # 实例化组件以获取其配置好的 APIRouter 实例
            component_instance = router_class()
            server = get_global_server()
            # 生成唯一的 URL 前缀，格式为 /plugins/{plugin_name}
            prefix = f"/plugins/{info.plugin_name}"
            # 将插件的路由包含到主应用中
            server.app.include_router(component_instance.router, prefix=prefix, tags=[info.plugin_name])

            logger.debug(f"路由组件 '{info.name}' 已挂载到: {prefix}")
            return True
        except Exception as e:
            logger.error(f"注册路由组件时出错: {e}", exc_info=True)
            return False

    def _register_adapter(self, info: ComponentInfo, cls: ComponentClassType) -> bool:
        """
        注册 Adapter 组件到 Adapter 特定注册表。

        Args:
            info: Adapter 组件的元数据信息
            cls: Adapter 组件的类定义

        Returns:
            注册成功返回 True
        """
        adapter_info = cast(AdapterInfo, info)
        adapter_class = cast(type[BaseAdapter], cls)
        _assign_plugin_attrs(adapter_class, info.plugin_name, self.get_plugin_config(info.plugin_name) or {})
        self._adapter_registry[info.name] = adapter_class
        if adapter_info.enabled:
            self._enabled_adapter_registry[info.name] = adapter_class
        return True

    # =================================================================
    # == 组件状态管理 (Component State Management)
    # == 委托给 ComponentStateManager 处理
    # =================================================================

    def enable_component(self, component_name: str, component_type: ComponentType) -> bool:
        """
        全局启用一个组件。

        Args:
            component_name: 组件名称
            component_type: 组件类型

        Returns:
            启用成功返回 True，失败返回 False
        """
        return self._state_manager.enable_component(component_name, component_type)

    async def disable_component(self, component_name: str, component_type: ComponentType) -> bool:
        """
        全局禁用一个组件。

        Args:
            component_name: 组件名称
            component_type: 组件类型

        Returns:
            禁用成功返回 True，失败返回 False
        """
        return await self._state_manager.disable_component(component_name, component_type)

    # =================================================================
    # == 局部状态管理 (Local State Management) - 委托给 ComponentStateManager
    # =================================================================

    def set_local_component_state(
        self, stream_id: str, component_name: str, component_type: ComponentType, enabled: bool
    ) -> bool:
        """
        为指定的会话（stream_id）设置组件的局部（临时）状态。

        这允许在单个对话流中动态启用或禁用组件，而不影响全局设置。

        Args:
            stream_id: 唯一的会话ID
            component_name: 组件名称
            component_type: 组件类型
            enabled: True 表示启用，False 表示禁用

        Returns:
            设置成功返回 True，如果组件类型不支持局部状态则返回 False
        """
        return self._state_manager.set_local_component_state(stream_id, component_name, component_type, enabled)

    def clear_local_component_states(self, stream_id: str) -> None:
        """
        清除指定会话的所有局部状态。

        当会话结束时应调用此方法来清理资源。

        Args:
            stream_id: 要清除状态的会话ID
        """
        self._state_manager.clear_local_component_states(stream_id)

    def is_component_available(
        self, component_name: str, component_type: ComponentType, stream_id: str | None = None
    ) -> bool:
        """
        检查一个组件在给定上下文中是否可用。

        检查顺序:
            1. 组件是否存在
            2. (如果提供了 stream_id) 是否有局部状态覆盖
            3. 全局启用状态

        Args:
            component_name: 组件名称
            component_type: 组件类型
            stream_id: 会话ID（可选）

        Returns:
            如果组件可用则返回 True
        """
        return self._state_manager.is_component_available(component_name, component_type, stream_id)

    # =================================================================
    # == 组件查询方法 (Component Query Methods)
    # =================================================================

    def get_component_info(
        self, component_name: str, component_type: ComponentType | None = None
    ) -> ComponentInfo | None:
        """
        获取组件信息，支持自动命名空间解析。

        如果只提供 component_name，它会尝试在所有类型中查找。如果找到多个同名但
        不同类型的组件，会发出警告并返回第一个找到的。

        Args:
            component_name: 组件名称，可以是原始名称或命名空间化的名称 (如 "action.my_action")
            component_type: 组件类型（可选）。如果提供，将只在该类型中查找

        Returns:
            找到的组件信息对象，或 None
        """
        # 1. 如果已经是命名空间化的名称，直接查找
        if "." in component_name:
            return self._components.get(component_name)

        # 2. 如果指定了组件类型，构造命名空间化的名称查找
        if component_type:
            return self._components.get(f"{component_type.value}.{component_name}")

        # 3. 如果没有指定类型，遍历所有类型查找
        candidates = [
            info
            for c_type in ComponentType
            if (info := self._components.get(f"{c_type.value}.{component_name}"))
        ]

        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            logger.warning(f"组件名称 '{component_name}' 在多个类型中存在，返回第一个匹配项")
            return candidates[0]
        return None

    def get_component_class(
        self, component_name: str, component_type: ComponentType | None = None
    ) -> ComponentClassType | None:
        """
        获取组件的类定义，支持自动命名空间解析。

        逻辑与 get_component_info 类似。

        Args:
            component_name: 组件名称
            component_type: 组件类型（可选）

        Returns:
            找到的组件类，或 None
        """
        # 1. 如果已经是命名空间化的名称，直接查找
        if "." in component_name:
            return self._components_classes.get(component_name)

        # 2. 如果指定了组件类型，构造命名空间化的名称查找
        if component_type:
            return self._components_classes.get(f"{component_type.value}.{component_name}")

        # 3. 复用 get_component_info 的查找逻辑
        info = self.get_component_info(component_name)
        if info:
            return self._components_classes.get(f"{info.component_type.value}.{info.name}")
        return None

    def get_components_by_type(self, component_type: ComponentType) -> dict[str, ComponentInfo]:
        """
        获取指定类型的所有已注册组件（无论是否启用）。

        Args:
            component_type: 要查询的组件类型

        Returns:
            组件名称到组件信息的字典（副本）
        """
        return self._components_by_type.get(component_type, {}).copy()

    def get_enabled_components_by_type(
        self, component_type: ComponentType, stream_id: str | None = None
    ) -> dict[str, ComponentInfo]:
        """
        获取指定类型的所有可用组件。

        这会同时考虑全局启用状态和 stream_id 对应的局部状态。

        Args:
            component_type: 要查询的组件类型
            stream_id: 会话ID，用于检查局部状态覆盖（可选）

        Returns:
            一个包含可用组件名称和信息的字典
        """
        return {
            name: info
            for name, info in self.get_components_by_type(component_type).items()
            if self.is_component_available(name, component_type, stream_id)
        }

    # =================================================================
    # == 特定类型查询方法 (Type-Specific Query Methods)
    # =================================================================

    # --- Action ---
    def get_action_registry(self) -> dict[str, type[BaseAction]]:
        """获取所有已注册的 Action 类。"""
        return self._action_registry.copy()

    def get_default_actions(self, stream_id: str | None = None) -> dict[str, ActionInfo]:
        """
        获取所有可用的 Action 信息（考虑全局和局部状态）。

        Args:
            stream_id: 会话ID，用于检查局部状态覆盖（可选）

        Returns:
            可用的 Action 名称到信息的字典
        """
        return cast(
            dict[str, ActionInfo],
            self.get_enabled_components_by_type(ComponentType.ACTION, stream_id),
        )

    def get_registered_action_info(self, action_name: str) -> ActionInfo | None:
        """
        获取指定 Action 的信息。

        Args:
            action_name: Action 名称

        Returns:
            ActionInfo 对象，如果不存在则返回 None
        """
        info = self.get_component_info(action_name, ComponentType.ACTION)
        return info if isinstance(info, ActionInfo) else None

    # --- PlusCommand ---
    def get_plus_command_registry(self) -> dict[str, type[PlusCommand]]:
        """获取所有已注册的 PlusCommand 类。"""
        return self._plus_command_registry.copy()

    def get_available_plus_commands_info(self, stream_id: str | None = None) -> dict[str, PlusCommandInfo]:
        """
        获取所有可用的 PlusCommand 信息（考虑全局和局部状态）。

        Args:
            stream_id: 会话ID，用于检查局部状态覆盖（可选）

        Returns:
            可用的 PlusCommand 名称到信息的字典
        """
        return cast(
            dict[str, PlusCommandInfo],
            self.get_enabled_components_by_type(ComponentType.PLUS_COMMAND, stream_id),
        )

    def get_registered_plus_command_info(self, command_name: str) -> PlusCommandInfo | None:
        """
        获取指定 PlusCommand 的信息。

        Args:
            command_name: 命令名称

        Returns:
            PlusCommandInfo 对象，如果不存在则返回 None
        """
        info = self.get_component_info(command_name, ComponentType.PLUS_COMMAND)
        return info if isinstance(info, PlusCommandInfo) else None

    # --- Tool ---
    def get_tool_registry(self) -> dict[str, type[BaseTool]]:
        """获取所有已注册的 Tool 类。"""
        return self._tool_registry.copy()

    def get_llm_available_tools(self, stream_id: str | None = None) -> dict[str, type[BaseTool]]:
        """
        获取所有对 LLM 可用的 Tool 类（考虑全局和局部状态）。

        Args:
            stream_id: 会话ID，用于检查局部状态覆盖（可选）

        Returns:
            可用的 Tool 名称到类的字典
        """
        return {
            name: cls
            for name, cls in self._tool_registry.items()
            if self.is_component_available(name, ComponentType.TOOL, stream_id)
        }

    def get_registered_tool_info(self, tool_name: str) -> ToolInfo | None:
        """
        获取指定 Tool 的信息。

        Args:
            tool_name: 工具名称

        Returns:
            ToolInfo 对象，如果不存在则返回 None
        """
        info = self.get_component_info(tool_name, ComponentType.TOOL)
        return info if isinstance(info, ToolInfo) else None

    # --- EventHandler ---
    def get_event_handler_registry(self) -> dict[str, type[BaseEventHandler]]:
        """获取所有已注册的 EventHandler 类。"""
        return self._event_handler_registry.copy()

    def get_enabled_event_handlers(self) -> dict[str, type[BaseEventHandler]]:
        """
        获取所有已启用的 EventHandler 类。

        会检查组件的全局启用状态。

        Returns:
            可用的 EventHandler 名称到类的字典
        """
        return {
            name: cls
            for name, cls in self._event_handler_registry.items()
            if self.is_component_available(name, ComponentType.EVENT_HANDLER)
        }

    def get_registered_event_handler_info(self, handler_name: str) -> EventHandlerInfo | None:
        """
        获取指定 EventHandler 的信息。

        Args:
            handler_name: 事件处理器名称

        Returns:
            EventHandlerInfo 对象，如果不存在则返回 None
        """
        info = self.get_component_info(handler_name, ComponentType.EVENT_HANDLER)
        return info if isinstance(info, EventHandlerInfo) else None

    # --- Chatter ---
    def get_chatter_registry(self) -> dict[str, type[BaseChatter]]:
        """获取所有已注册的 Chatter 类。"""
        return self._chatter_registry.copy()

    def get_enabled_chatter_registry(self, stream_id: str | None = None) -> dict[str, type[BaseChatter]]:
        """
        获取所有可用的 Chatter 类（考虑全局和局部状态）。

        Args:
            stream_id: 会话ID，用于检查局部状态覆盖（可选）

        Returns:
            可用的 Chatter 名称到类的字典
        """
        return {
            name: cls
            for name, cls in self._chatter_registry.items()
            if self.is_component_available(name, ComponentType.CHATTER, stream_id)
        }

    def get_registered_chatter_info(self, chatter_name: str) -> ChatterInfo | None:
        """
        获取指定 Chatter 的信息。

        Args:
            chatter_name: Chatter 名称

        Returns:
            ChatterInfo 对象，如果不存在则返回 None
        """
        info = self.get_component_info(chatter_name, ComponentType.CHATTER)
        return info if isinstance(info, ChatterInfo) else None

    # --- InterestCalculator ---
    def get_interest_calculator_registry(self) -> dict[str, type[BaseInterestCalculator]]:
        """获取所有已注册的 InterestCalculator 类。"""
        return self._interest_calculator_registry.copy()

    def get_enabled_interest_calculator_registry(self) -> dict[str, type[BaseInterestCalculator]]:
        """
        获取所有已启用的 InterestCalculator 类。

        会检查组件的全局启用状态。

        Returns:
            可用的 InterestCalculator 名称到类的字典
        """
        return {
            name: cls
            for name, cls in self._interest_calculator_registry.items()
            if self.is_component_available(name, ComponentType.INTEREST_CALCULATOR)
        }

    # --- Prompt ---
    def get_prompt_registry(self) -> dict[str, type[BasePrompt]]:
        """获取所有已注册的 Prompt 类。"""
        return self._prompt_registry.copy()

    def get_enabled_prompt_registry(self) -> dict[str, type[BasePrompt]]:
        """
        获取所有已启用的 Prompt 类。

        会检查组件的全局启用状态。

        Returns:
            可用的 Prompt 名称到类的字典
        """
        return {
            name: cls
            for name, cls in self._prompt_registry.items()
            if self.is_component_available(name, ComponentType.PROMPT)
        }

    # --- Adapter ---
    def get_adapter_registry(self) -> dict[str, type[BaseAdapter]]:
        """获取所有已注册的 Adapter 类。"""
        return self._adapter_registry.copy()

    def get_enabled_adapter_registry(self) -> dict[str, type[BaseAdapter]]:
        """获取所有已启用的 Adapter 类。"""
        return self._enabled_adapter_registry.copy()

    # --- Command (旧版兼容) ---
    def get_command_registry(self) -> dict[str, type[BaseCommand]]:
        """获取 Command 注册表（旧版兼容）。"""
        return self._command_registry.copy()

    def get_command_patterns(self) -> dict[Pattern, str]:
        """获取 Command 模式注册表（旧版兼容）。"""
        return self._command_patterns.copy()

    def get_registered_command_info(self, command_name: str) -> CommandInfo | None:
        """
        获取 Command 信息（旧版兼容）。

        Args:
            command_name: 命令名称

        Returns:
            CommandInfo 对象，如果不存在则返回 None
        """
        info = self.get_component_info(command_name, ComponentType.COMMAND)
        return info if isinstance(info, CommandInfo) else None

    def find_command_by_text(self, text: str) -> tuple[type[BaseCommand], dict, CommandInfo] | None:
        """
        根据文本查找匹配的命令（旧版兼容）。

        Args:
            text: 输入文本

        Returns:
            元组 (命令类, 匹配的命名组, 命令信息) 或 None
        """
        for pattern, command_name in self._command_patterns.items():
            if match := pattern.match(text):
                command_info = self.get_registered_command_info(command_name)
                if command_info:
                    return (
                        self._command_registry[command_name],
                        match.groupdict(),
                        command_info,
                    )
        return None

    # =================================================================
    # == 插件查询方法 (Plugin Query Methods)
    # =================================================================

    def get_plugin_info(self, plugin_name: str) -> PluginInfo | None:
        """
        获取指定插件的信息。

        Args:
            plugin_name: 插件名称

        Returns:
            PluginInfo 对象，如果不存在则返回 None
        """
        return self._plugins.get(plugin_name)

    def get_all_plugins(self) -> dict[str, PluginInfo]:
        """获取所有已注册的插件。"""
        return self._plugins.copy()

    def get_plugin_components(self, plugin_name: str) -> list[ComponentInfo]:
        """
        获取指定插件下的所有组件信息。

        Args:
            plugin_name: 插件名称

        Returns:
            该插件的组件信息列表，如果插件不存在则返回空列表
        """
        plugin_info = self.get_plugin_info(plugin_name)
        return plugin_info.components if plugin_info else []

    def get_plugin_config(self, plugin_name: str) -> dict | None:
        """
        获取插件的配置信息。

        它会首先尝试从已加载的插件实例中获取，如果失败，则尝试从文件系统读取。

        Args:
            plugin_name: 插件名称

        Returns:
            插件的配置字典，如果找不到则返回 None
        """
        # 延迟导入以避免循环依赖
        from src.plugin_system.core.plugin_manager import plugin_manager

        # 首先尝试从已加载的插件实例获取配置
        plugin_instance = plugin_manager.get_plugin_instance(plugin_name)
        if plugin_instance and plugin_instance.config:
            return plugin_instance.config

        # 如果插件实例不存在，尝试从配置文件读取
        try:
            config_path = Path("config") / "plugins" / plugin_name / "config.toml"
            if config_path.exists():
                with open(config_path, encoding="utf-8") as f:
                    return toml.load(f)
        except Exception as e:
            logger.debug(f"读取插件 {plugin_name} 配置文件失败: {e}")
        return None

    # =================================================================
    # == MCP 工具方法 (MCP Tool Methods)
    # =================================================================

    async def load_mcp_tools(self) -> None:
        """
        异步加载所有 MCP (Model-Copilot-Plugin) 工具。

        此方法会动态导入并实例化 MCP 工具适配器。为避免重复加载，它会检查一个标志位。
        """
        if self._mcp_tools_loaded:
            return

        try:
            from .mcp_tool_adapter import load_mcp_tools_as_adapters
            logger.info("开始加载 MCP 工具...")
            self._mcp_tools = await load_mcp_tools_as_adapters()
            self._mcp_tools_loaded = True
            logger.info(f"MCP 工具加载完成，共 {len(self._mcp_tools)} 个工具")
        except Exception as e:
            logger.error(f"加载 MCP 工具失败: {e}", exc_info=True)
            self._mcp_tools = []
            self._mcp_tools_loaded = True  # 标记为已尝试加载，避免重复失败

    def get_mcp_tools(self) -> list[Any]:
        """获取所有已加载的 MCP 工具适配器实例。"""
        return self._mcp_tools.copy()

    def is_mcp_tool(self, tool_name: str) -> bool:
        """
        检查一个工具名称是否代表一个 MCP 工具（基于命名约定）。

        Args:
            tool_name: 工具名称

        Returns:
            如果工具名以 "mcp_" 开头则返回 True
        """
        return tool_name.startswith("mcp_")

    # =================================================================
    # == 统计方法 (Statistics Methods)
    # =================================================================

    def get_registry_stats(self) -> dict[str, Any]:
        """
        获取注册中心的统计信息，用于调试和监控。

        Returns:
            包含各种统计数据的字典
        """
        # 按类型统计组件数量
        stats = {ct.value: 0 for ct in ComponentType}
        for component in self._components.values():
            stats[component.component_type.value] += 1

        return {
            "total_plugins": len(self._plugins),
            "total_components": len(self._components),
            "enabled_components": sum(1 for c in self._components.values() if c.enabled),
            "mcp_tools_loaded": len(self._mcp_tools),
            "components_by_type": stats,
        }


# --- 全局实例 ---
# 创建全局唯一的组件注册中心实例，供项目各处使用
component_registry = ComponentRegistry()

