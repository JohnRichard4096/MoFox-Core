"""
MCP 事件处理器
"""

import json
import asyncio
from typing import Dict, Any, Callable, Optional, List
from dataclasses import dataclass
from datetime import datetime
from src.common.logger import get_logger


logger = get_logger("mcp_event_handler")


@dataclass
class MCPEvent:
    """MCP 事件数据类"""
    
    event_type: str
    """事件类型"""
    
    data: Dict[str, Any]
    """事件数据"""
    
    timestamp: datetime
    """事件时间戳"""
    
    event_id: Optional[str] = None
    """事件 ID"""
    
    retry: Optional[int] = None
    """重试间隔（毫秒）"""


class MCPEventHandler:
    """MCP 事件处理器"""
    
    def __init__(self):
        self._event_handlers: Dict[str, List[Callable]] = {}
        self._global_handlers: List[Callable] = []
        self._event_buffer: List[MCPEvent] = []
        self._buffer_size = 1000
        self._running = False
        
    def register_handler(self, event_type: str, handler: Callable[[MCPEvent], None]):
        """
        注册事件处理器
        
        Args:
            event_type: 事件类型
            handler: 事件处理函数
        """
        if event_type not in self._event_handlers:
            self._event_handlers[event_type] = []
        self._event_handlers[event_type].append(handler)
        logger.debug(f"注册事件处理器: {event_type}")
    
    def register_global_handler(self, handler: Callable[[MCPEvent], None]):
        """
        注册全局事件处理器（处理所有事件）
        
        Args:
            handler: 事件处理函数
        """
        self._global_handlers.append(handler)
        logger.debug("注册全局事件处理器")
    
    def unregister_handler(self, event_type: str, handler: Callable[[MCPEvent], None]):
        """
        取消注册事件处理器
        
        Args:
            event_type: 事件类型
            handler: 事件处理函数
        """
        if event_type in self._event_handlers:
            try:
                self._event_handlers[event_type].remove(handler)
                logger.debug(f"取消注册事件处理器: {event_type}")
            except ValueError:
                logger.warning(f"尝试取消注册不存在的事件处理器: {event_type}")
    
    def unregister_global_handler(self, handler: Callable[[MCPEvent], None]):
        """
        取消注册全局事件处理器
        
        Args:
            handler: 事件处理函数
        """
        try:
            self._global_handlers.remove(handler)
            logger.debug("取消注册全局事件处理器")
        except ValueError:
            logger.warning("尝试取消注册不存在的全局事件处理器")
    
    async def handle_event(self, event: MCPEvent):
        """
        处理单个事件
        
        Args:
            event: MCP 事件
        """
        logger.debug(f"处理事件: {event.event_type}")
        
        # 添加到事件缓冲区
        self._add_to_buffer(event)
        
        # 处理特定类型的事件处理器
        if event.event_type in self._event_handlers:
            for handler in self._event_handlers[event.event_type]:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(event)
                    else:
                        handler(event)
                except Exception as e:
                    logger.error(f"事件处理器执行失败: {e}", exc_info=True)
        
        # 处理全局事件处理器
        for handler in self._global_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.error(f"全局事件处理器执行失败: {e}", exc_info=True)
    
    def _add_to_buffer(self, event: MCPEvent):
        """
        添加事件到缓冲区
        
        Args:
            event: MCP 事件
        """
        self._event_buffer.append(event)
        
        # 如果缓冲区超过限制，移除最旧的事件
        if len(self._event_buffer) > self._buffer_size:
            self._event_buffer.pop(0)
    
    def get_recent_events(self, count: int = 10) -> List[MCPEvent]:
        """
        获取最近的事件
        
        Args:
            count: 获取的事件数量
            
        Returns:
            最近的事件列表
        """
        return self._event_buffer[-count:]
    
    def get_events_by_type(self, event_type: str, count: int = 10) -> List[MCPEvent]:
        """
        根据类型获取事件
        
        Args:
            event_type: 事件类型
            count: 获取的事件数量
            
        Returns:
            指定类型的事件列表
        """
        filtered_events = [e for e in self._event_buffer if e.event_type == event_type]
        return filtered_events[-count:]
    
    def clear_buffer(self):
        """清空事件缓冲区"""
        self._event_buffer.clear()
        logger.debug("清空事件缓冲区")
    
    def set_buffer_size(self, size: int):
        """
        设置缓冲区大小
        
        Args:
            size: 缓冲区大小
        """
        if size <= 0:
            raise ValueError("缓冲区大小必须大于 0")
        
        self._buffer_size = size
        
        # 如果当前缓冲区超过新大小，截断
        if len(self._event_buffer) > size:
            self._event_buffer = self._event_buffer[-size:]
        
        logger.debug(f"设置事件缓冲区大小: {size}")
    
    def get_handler_count(self) -> Dict[str, int]:
        """
        获取各类型事件处理器数量
        
        Returns:
            事件类型到处理器数量的映射
        """
        counts = {}
        for event_type, handlers in self._event_handlers.items():
            counts[event_type] = len(handlers)
        counts["global"] = len(self._global_handlers)
        return counts


def parse_sse_event(raw_data: str) -> Optional[MCPEvent]:
    """
    解析 SSE 事件数据
    
    Args:
        raw_data: 原始 SSE 数据
        
    Returns:
        解析后的 MCP 事件，如果解析失败返回 None
    """
    try:
        lines = raw_data.strip().split('\n')
        event_type = None
        event_data = None
        event_id = None
        retry = None
        
        for line in lines:
            line = line.strip()
            if line.startswith('event:'):
                event_type = line[6:].strip()
            elif line.startswith('data:'):
                data_str = line[5:].strip()
                if data_str:
                    try:
                        event_data = json.loads(data_str)
                    except json.JSONDecodeError:
                        # 如果不是 JSON，直接使用字符串
                        event_data = {"message": data_str}
            elif line.startswith('id:'):
                event_id = line[3:].strip()
            elif line.startswith('retry:'):
                try:
                    retry = int(line[6:].strip())
                except ValueError:
                    pass
        
        if event_type and event_data is not None:
            return MCPEvent(
                event_type=event_type,
                data=event_data,
                timestamp=datetime.now(),
                event_id=event_id,
                retry=retry
            )
        
        return None
        
    except Exception as e:
        logger.error(f"解析 SSE 事件失败: {e}")
        return None