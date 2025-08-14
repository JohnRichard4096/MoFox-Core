"""
MCP SSE 管理器

负责管理 MCP SSE 客户端的生命周期，集成到 MaiBot 主系统中。
"""

import asyncio
from typing import Optional, Dict, Any, Callable
from datetime import datetime

from .sse_client import MCPSSEClient
from .config import MCPSSEConfig
from .event_handler import MCPEvent
from .exceptions import MCPConnectionError, MCPReconnectError
from src.common.logger import get_logger


logger = get_logger("mcp_sse_manager")


class MCPSSEManager:
    """MCP SSE 管理器"""
    
    def __init__(self, config: MCPSSEConfig):
        """
        初始化 MCP SSE 管理器
        
        Args:
            config: MCP SSE 配置
        """
        self.config = config
        self.client: Optional[MCPSSEClient] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        
        logger.info("初始化 MCP SSE 管理器")
    
    async def start(self):
        """启动 MCP SSE 客户端"""
        if not self.config.enable:
            logger.info("MCP SSE 客户端未启用，跳过启动")
            return
        
        if self._running:
            logger.warning("MCP SSE 客户端已在运行")
            return
        
        try:
            # 创建客户端
            self.client = MCPSSEClient(self.config)
            
            # 注册默认事件处理器
            self._register_default_handlers()
            
            # 启动监听任务
            self._task = asyncio.create_task(self._run_client())
            self._running = True
            
            logger.info("MCP SSE 客户端启动成功")
            
        except Exception as e:
            logger.error(f"启动 MCP SSE 客户端失败: {e}", exc_info=True)
            await self.stop()
            raise
    
    async def stop(self):
        """停止 MCP SSE 客户端"""
        if not self._running:
            return
        
        logger.info("停止 MCP SSE 客户端")
        self._running = False
        
        # 停止客户端
        if self.client:
            self.client.stop()
        
        # 取消任务
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        # 断开连接
        if self.client:
            await self.client.disconnect()
            self.client = None
        
        self._task = None
        logger.info("MCP SSE 客户端已停止")
    
    async def _run_client(self):
        """运行客户端监听循环"""
        if not self.client:
            return
        
        try:
            await self.client.start_listening()
        except MCPReconnectError as e:
            logger.error(f"MCP SSE 客户端重连失败: {e}")
        except Exception as e:
            logger.error(f"MCP SSE 客户端运行异常: {e}", exc_info=True)
        finally:
            self._running = False
    
    def _register_default_handlers(self):
        """注册默认事件处理器"""
        if not self.client:
            return
        
        # 注册全局事件处理器用于日志记录
        self.client.register_global_event_handler(self._log_event_handler)
        
        # 注册一些常见事件的处理器
        self.client.register_event_handler("system.status", self._handle_system_status)
        self.client.register_event_handler("chat.message", self._handle_chat_message)
        self.client.register_event_handler("user.action", self._handle_user_action)
        
        logger.debug("注册默认 MCP 事件处理器")
    
    def _log_event_handler(self, event: MCPEvent):
        """全局事件日志处理器"""
        if self.config.enable_event_logging:
            logger.debug(f"MCP 事件: {event.event_type} - {event.data}")
    
    def _handle_system_status(self, event: MCPEvent):
        """处理系统状态事件"""
        logger.info(f"收到系统状态事件: {event.data}")
        # 这里可以添加具体的系统状态处理逻辑
    
    def _handle_chat_message(self, event: MCPEvent):
        """处理聊天消息事件"""
        logger.info(f"收到聊天消息事件: {event.data}")
        # 这里可以添加具体的聊天消息处理逻辑
        # 例如：触发 MaiBot 的回复逻辑
    
    def _handle_user_action(self, event: MCPEvent):
        """处理用户行为事件"""
        logger.info(f"收到用户行为事件: {event.data}")
        # 这里可以添加具体的用户行为处理逻辑
    
    def register_event_handler(self, event_type: str, handler: Callable[[MCPEvent], None]):
        """
        注册自定义事件处理器
        
        Args:
            event_type: 事件类型
            handler: 事件处理函数
        """
        if self.client:
            self.client.register_event_handler(event_type, handler)
            logger.debug(f"注册自定义事件处理器: {event_type}")
        else:
            logger.warning("客户端未初始化，无法注册事件处理器")
    
    def register_global_event_handler(self, handler: Callable[[MCPEvent], None]):
        """
        注册全局事件处理器
        
        Args:
            handler: 事件处理函数
        """
        if self.client:
            self.client.register_global_event_handler(handler)
            logger.debug("注册全局事件处理器")
        else:
            logger.warning("客户端未初始化，无法注册全局事件处理器")
    
    def is_running(self) -> bool:
        """检查是否正在运行"""
        return self._running
    
    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self.client.is_connected() if self.client else False
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息
        
        Returns:
            统计信息字典
        """
        if not self.client:
            return {
                "enabled": self.config.enable,
                "running": False,
                "connected": False,
                "client_initialized": False
            }
        
        stats = self.client.get_stats()
        stats.update({
            "enabled": self.config.enable,
            "client_initialized": True,
            "server_url": self.config.server_url,
            "subscribed_events": self.config.subscribed_events,
        })
        
        return stats
    
    def get_recent_events(self, count: int = 10):
        """
        获取最近的事件
        
        Args:
            count: 获取的事件数量
            
        Returns:
            最近的事件列表
        """
        if self.client:
            return self.client.get_recent_events(count)
        return []


# 全局 MCP SSE 管理器实例
_mcp_sse_manager: Optional[MCPSSEManager] = None


def get_mcp_sse_manager() -> Optional[MCPSSEManager]:
    """获取全局 MCP SSE 管理器实例"""
    return _mcp_sse_manager


def initialize_mcp_sse_manager(config: MCPSSEConfig) -> MCPSSEManager:
    """
    初始化全局 MCP SSE 管理器
    
    Args:
        config: MCP SSE 配置
        
    Returns:
        MCP SSE 管理器实例
    """
    global _mcp_sse_manager
    
    if _mcp_sse_manager:
        logger.warning("MCP SSE 管理器已初始化")
        return _mcp_sse_manager
    
    _mcp_sse_manager = MCPSSEManager(config)
    logger.info("全局 MCP SSE 管理器初始化完成")
    return _mcp_sse_manager


async def start_mcp_sse_manager():
    """启动全局 MCP SSE 管理器"""
    if _mcp_sse_manager:
        await _mcp_sse_manager.start()
    else:
        logger.warning("MCP SSE 管理器未初始化")


async def stop_mcp_sse_manager():
    """停止全局 MCP SSE 管理器"""
    if _mcp_sse_manager:
        await _mcp_sse_manager.stop()