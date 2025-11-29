"""
Kokoro Flow Chatter (心流聊天器) 插件入口

这是一个专为私聊场景设计的AI聊天插件，实现从"消息响应者"到"对话体验者"的转变。

核心特点：
- 心理状态驱动的交互模型
- 连续的时间观念和等待体验  
- 深度情感连接和长期关系维护
- 状态机驱动的交互节奏

切换逻辑：
- 当 enable = true 时，KFC 接管所有私聊消息
- 当 enable = false 时，私聊消息由 AFC (Affinity Flow Chatter) 处理
"""

import asyncio
from typing import Any, ClassVar

from src.common.logger import get_logger
from src.config.config import global_config
from src.plugin_system.apis.plugin_register_api import register_plugin
from src.plugin_system.base.base_plugin import BasePlugin
from src.plugin_system.base.component_types import ComponentInfo

logger = get_logger("kokoro_flow_chatter_plugin")


@register_plugin
class KokoroFlowChatterPlugin(BasePlugin):
    """
    心流聊天器插件
    
    专为私聊场景设计的深度情感交互处理器。
    
    Features:
    - KokoroFlowChatter: 核心聊天处理器组件
    - SessionManager: 会话管理，支持持久化
    - BackgroundScheduler: 后台调度，处理等待超时
    - PromptGenerator: 动态提示词生成
    - ActionExecutor: 动作解析和执行
    """
    
    plugin_name: str = "kokoro_flow_chatter"
    enable_plugin: bool = True
    dependencies: ClassVar[list[str]] = []
    python_dependencies: ClassVar[list[str]] = []
    config_file_name: str = "config.toml"
    
    # 配置schema留空，使用config.toml直接配置
    config_schema: ClassVar[dict[str, Any]] = {}
    
    # 后台任务
    _session_manager = None
    _scheduler = None
    _initialization_task = None
    
    def get_plugin_components(self) -> list[tuple[ComponentInfo, type]]:
        """
        返回插件包含的组件列表
        
        根据 global_config.kokoro_flow_chatter.enable 决定是否注册 KFC。
        如果 enable = false，返回空列表，私聊将由 AFC 处理。
        """
        components: list[tuple[ComponentInfo, type]] = []
        
        # 检查是否启用 KFC
        kfc_enabled = True
        if global_config and hasattr(global_config, 'kokoro_flow_chatter'):
            kfc_enabled = global_config.kokoro_flow_chatter.enable
        
        if not kfc_enabled:
            logger.info("KFC 已禁用 (enable = false)，私聊将由 AFC 处理")
            return components
        
        try:
            # 导入核心聊天处理器
            from .chatter import KokoroFlowChatter
            
            components.append((
                KokoroFlowChatter.get_chatter_info(),
                KokoroFlowChatter
            ))
            logger.debug("成功加载 KokoroFlowChatter 组件，KFC 将接管私聊")
            
        except Exception as e:
            logger.error(f"加载 KokoroFlowChatter 时出错: {e}")
        
        return components
    
    async def on_plugin_load(self) -> bool:
        """
        插件加载时的初始化逻辑
        
        如果 KFC 被禁用，跳过初始化。
        
        Returns:
            bool: 是否加载成功
        """
        # 检查是否启用 KFC
        kfc_enabled = True
        if global_config and hasattr(global_config, 'kokoro_flow_chatter'):
            kfc_enabled = global_config.kokoro_flow_chatter.enable
        
        if not kfc_enabled:
            logger.info("KFC 已禁用，跳过初始化")
            self._is_started = False
            return True
        
        try:
            logger.info("正在初始化 Kokoro Flow Chatter 插件...")
            
            # 初始化会话管理器
            from .session_manager import initialize_session_manager
            
            session_config = self.config.get("kokoro_flow_chatter", {}).get("session", {})
            self._session_manager = await initialize_session_manager(
                data_dir=session_config.get("data_dir", "data/kokoro_flow_chatter/sessions"),
                max_session_age_days=session_config.get("max_session_age_days", 30),
                auto_save_interval=session_config.get("auto_save_interval", 300),
            )
            
            # 初始化调度器
            from .kfc_scheduler_adapter import initialize_scheduler
            
            # 从 global_config 读取配置
            check_interval = 10.0
            if global_config and hasattr(global_config, 'kokoro_flow_chatter'):
                # 使用简化后的配置结构
                pass  # check_interval 保持默认值
            
            self._scheduler = await initialize_scheduler(
                check_interval=check_interval,
            )
            
            self._is_started = True
            logger.info("Kokoro Flow Chatter 插件初始化完成")
            return True
            
        except Exception as e:
            logger.error(f"Kokoro Flow Chatter 插件初始化失败: {e}")
            return False
    
    async def on_plugin_unload(self) -> bool:
        """
        插件卸载时的清理逻辑
        
        Returns:
            bool: 是否卸载成功
        """
        try:
            logger.info("正在关闭 Kokoro Flow Chatter 插件...")
            
            # 停止调度器
            if self._scheduler:
                from .kfc_scheduler_adapter import shutdown_scheduler
                await shutdown_scheduler()
                self._scheduler = None
            
            # 停止会话管理器
            if self._session_manager:
                await self._session_manager.stop()
                self._session_manager = None
            
            self._is_started = False
            logger.info("Kokoro Flow Chatter 插件已关闭")
            return True
            
        except Exception as e:
            logger.error(f"Kokoro Flow Chatter 插件关闭失败: {e}")
            return False
    
    def register_plugin(self) -> bool:
        """
        注册插件及其所有组件
        
        重写父类方法，添加异步初始化逻辑
        """
        # 先调用父类的注册逻辑
        result = super().register_plugin()
        
        if result:
            # 在后台启动异步初始化
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    self._initialization_task = asyncio.create_task(
                        self.on_plugin_load()
                    )
                else:
                    # 如果事件循环未运行，稍后初始化
                    logger.debug("事件循环未运行，将延迟初始化")
            except RuntimeError:
                logger.debug("无法获取事件循环，将延迟初始化")
        
        return result
    
    @property
    def is_started(self) -> bool:
        """插件是否已启动"""
        return self._is_started
    
    def get_plugin_stats(self) -> dict[str, Any]:
        """获取插件统计信息"""
        stats: dict[str, Any] = {
            "is_started": self._is_started,
            "has_session_manager": self._session_manager is not None,
            "has_scheduler": self._scheduler is not None,
        }
        
        if self._scheduler:
            stats["scheduler_stats"] = self._scheduler.get_stats()
        
        if self._session_manager:
            # 异步获取会话统计需要在异步上下文中调用
            stats["session_manager_active"] = True
        
        return stats
