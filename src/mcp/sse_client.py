"""
MCP Server-Sent Events 客户端
"""

import asyncio
import aiohttp
import ssl
from typing import Optional, Dict, Any, Callable
from datetime import datetime
import time
import json

from .config import MCPSSEConfig
from .event_handler import MCPEventHandler, MCPEvent, parse_sse_event
from .exceptions import (
    MCPConnectionError,
    MCPAuthenticationError,
    MCPTimeoutError,
    MCPReconnectError,
    MCPEventError
)
from src.common.logger import get_logger


logger = get_logger("mcp_sse_client")


class MCPSSEClient:
    """MCP Server-Sent Events 客户端"""
    
    def __init__(self, config: MCPSSEConfig):
        """
        初始化 MCP SSE 客户端
        
        Args:
            config: MCP SSE 配置
        """
        self.config = config
        self.event_handler = MCPEventHandler()
        
        # 连接状态
        self._session: Optional[aiohttp.ClientSession] = None
        self._response: Optional[aiohttp.ClientResponse] = None
        self._connected = False
        self._running = False
        
        # 重连状态
        self._reconnect_attempts = 0
        self._last_event_id: Optional[str] = None
        
        # 统计信息
        self._connection_start_time: Optional[datetime] = None
        self._total_events_received = 0
        self._last_event_time: Optional[datetime] = None
        
        # 设置事件缓冲区大小
        self.event_handler.set_buffer_size(config.event_buffer_size)
        
        logger.info(f"初始化 MCP SSE 客户端: {config.server_url}")
    
    async def connect(self) -> bool:
        """
        连接到 MCP 服务器
        
        Returns:
            连接是否成功
        """
        if self._connected:
            logger.warning("客户端已连接")
            return True
        
        try:
            # 创建 SSL 上下文
            ssl_context = None
            if self.config.server_url.startswith('https://'):
                ssl_context = ssl.create_default_context()
                if not self.config.verify_ssl:
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE
                
                if self.config.ssl_cert_path and self.config.ssl_key_path:
                    ssl_context.load_cert_chain(
                        self.config.ssl_cert_path,
                        self.config.ssl_key_path
                    )
            
            # 创建会话
            timeout = aiohttp.ClientTimeout(
                connect=self.config.connection_timeout,
                sock_read=self.config.read_timeout
            )
            
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers=self.config.get_headers()
            )
            
            # 建立连接
            headers = {}
            if self._last_event_id:
                headers['Last-Event-ID'] = self._last_event_id
            
            logger.info(f"连接到 MCP 服务器: {self.config.server_url}")
            
            self._response = await self._session.get(
                self.config.server_url,
                headers=headers,
                ssl=ssl_context
            )
            
            # 检查响应状态
            if self._response.status == 401:
                raise MCPAuthenticationError(
                    "认证失败",
                    url=self.config.server_url,
                    status_code=self._response.status
                )
            elif self._response.status != 200:
                raise MCPConnectionError(
                    f"连接失败: HTTP {self._response.status}",
                    url=self.config.server_url,
                    status_code=self._response.status
                )
            
            # 检查内容类型
            content_type = self._response.headers.get('Content-Type', '')
            if 'text/event-stream' not in content_type:
                raise MCPConnectionError(
                    f"无效的内容类型: {content_type}",
                    url=self.config.server_url
                )
            
            self._connected = True
            self._connection_start_time = datetime.now()
            self._reconnect_attempts = 0
            
            logger.info("成功连接到 MCP 服务器")
            return True
            
        except asyncio.TimeoutError:
            raise MCPTimeoutError(
                "连接超时",
                url=self.config.server_url
            )
        except Exception as e:
            await self._cleanup_connection()
            if isinstance(e, (MCPConnectionError, MCPAuthenticationError, MCPTimeoutError)):
                raise
            else:
                raise MCPConnectionError(f"连接失败: {str(e)}", url=self.config.server_url)
    
    async def disconnect(self):
        """断开连接"""
        logger.info("断开 MCP 服务器连接")
        self._running = False
        await self._cleanup_connection()
    
    async def _cleanup_connection(self):
        """清理连接资源"""
        self._connected = False
        
        if self._response:
            self._response.close()
            self._response = None
        
        if self._session:
            await self._session.close()
            self._session = None
    
    async def start_listening(self):
        """开始监听事件"""
        if not self.config.enable:
            logger.warning("MCP SSE 客户端未启用")
            return
        
        self._running = True
        
        while self._running:
            try:
                if not self._connected:
                    await self.connect()
                
                await self._listen_events()
                
            except (MCPConnectionError, MCPTimeoutError) as e:
                logger.error(f"连接错误: {e}")
                await self._cleanup_connection()
                
                if self.config.enable_reconnect:
                    await self._handle_reconnect()
                else:
                    break
                    
            except Exception as e:
                logger.error(f"监听事件时发生未知错误: {e}", exc_info=True)
                await self._cleanup_connection()
                
                if self.config.enable_reconnect:
                    await self._handle_reconnect()
                else:
                    break
        
        await self._cleanup_connection()
        logger.info("停止监听 MCP 事件")
    
    async def _listen_events(self):
        """监听事件流"""
        if not self._response:
            raise MCPConnectionError("没有活动的连接")
        
        logger.info("开始监听 MCP 事件流")
        
        buffer = ""
        
        async for chunk in self._response.content.iter_chunked(1024):
            if not self._running:
                break
            
            try:
                # 解码数据
                data = chunk.decode('utf-8')
                buffer += data
                
                # 处理完整的事件
                while '\n\n' in buffer:
                    event_data, buffer = buffer.split('\n\n', 1)
                    if event_data.strip():
                        await self._process_event_data(event_data)
                        
            except UnicodeDecodeError as e:
                logger.error(f"解码事件数据失败: {e}")
                continue
            except Exception as e:
                logger.error(f"处理事件数据失败: {e}", exc_info=True)
                continue
    
    async def _process_event_data(self, event_data: str):
        """
        处理事件数据
        
        Args:
            event_data: 原始事件数据
        """
        try:
            # 解析 SSE 事件
            event = parse_sse_event(event_data)
            if not event:
                return
            
            # 更新统计信息
            self._total_events_received += 1
            self._last_event_time = event.timestamp
            
            if event.event_id:
                self._last_event_id = event.event_id
            
            # 检查事件订阅
            if self.config.subscribed_events:
                if event.event_type not in self.config.subscribed_events:
                    logger.debug(f"跳过未订阅的事件类型: {event.event_type}")
                    return
            
            # 记录事件日志
            if self.config.enable_event_logging:
                logger.info(f"收到 MCP 事件: {event.event_type}")
                logger.debug(f"事件数据: {event.data}")
            
            # 处理事件
            await self.event_handler.handle_event(event)
            
        except Exception as e:
            logger.error(f"处理事件失败: {e}", exc_info=True)
            raise MCPEventError(f"处理事件失败: {str(e)}")
    
    async def _handle_reconnect(self):
        """处理重连逻辑"""
        if not self.config.enable_reconnect:
            return
        
        self._reconnect_attempts += 1
        
        # 检查最大重连次数
        if (self.config.max_reconnect_attempts > 0 and 
            self._reconnect_attempts > self.config.max_reconnect_attempts):
            raise MCPReconnectError(
                "超过最大重连次数",
                attempts=self._reconnect_attempts,
                max_attempts=self.config.max_reconnect_attempts
            )
        
        # 计算重连延迟（指数退避）
        delay = min(
            self.config.initial_reconnect_delay * (
                self.config.reconnect_backoff_factor ** (self._reconnect_attempts - 1)
            ),
            self.config.max_reconnect_delay
        )
        
        logger.info(f"第 {self._reconnect_attempts} 次重连尝试，延迟 {delay:.2f} 秒")
        await asyncio.sleep(delay)
    
    def stop(self):
        """停止客户端"""
        logger.info("停止 MCP SSE 客户端")
        self._running = False
    
    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self._connected
    
    def is_running(self) -> bool:
        """检查是否正在运行"""
        return self._running
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取客户端统计信息
        
        Returns:
            统计信息字典
        """
        stats = {
            "connected": self._connected,
            "running": self._running,
            "reconnect_attempts": self._reconnect_attempts,
            "total_events_received": self._total_events_received,
            "connection_start_time": self._connection_start_time,
            "last_event_time": self._last_event_time,
            "last_event_id": self._last_event_id,
        }
        
        if self._connection_start_time:
            stats["uptime_seconds"] = (datetime.now() - self._connection_start_time).total_seconds()
        
        # 添加事件处理器统计
        stats["event_handlers"] = self.event_handler.get_handler_count()
        
        return stats
    
    def register_event_handler(self, event_type: str, handler: Callable[[MCPEvent], None]):
        """
        注册事件处理器
        
        Args:
            event_type: 事件类型
            handler: 事件处理函数
        """
        self.event_handler.register_handler(event_type, handler)
    
    def register_global_event_handler(self, handler: Callable[[MCPEvent], None]):
        """
        注册全局事件处理器
        
        Args:
            handler: 事件处理函数
        """
        self.event_handler.register_global_handler(handler)
    
    def unregister_event_handler(self, event_type: str, handler: Callable[[MCPEvent], None]):
        """
        取消注册事件处理器
        
        Args:
            event_type: 事件类型
            handler: 事件处理函数
        """
        self.event_handler.unregister_handler(event_type, handler)
    
    def get_recent_events(self, count: int = 10):
        """
        获取最近的事件
        
        Args:
            count: 获取的事件数量
            
        Returns:
            最近的事件列表
        """
        return self.event_handler.get_recent_events(count)