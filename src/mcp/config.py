"""
MCP SSE 客户端配置类
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from src.config.config_base import ConfigBase


@dataclass
class MCPSSEConfig(ConfigBase):
    """MCP Server-Sent Events 客户端配置类"""

    enable: bool = False
    """是否启用 MCP SSE 客户端"""

    server_url: str = ""
    """MCP 服务器 SSE 端点 URL，例如: http://localhost:8080/events"""

    auth_key: str = ""
    """MCP 服务器认证密钥"""

    # 连接配置
    connection_timeout: int = 30
    """连接超时时间（秒）"""

    read_timeout: int = 60
    """读取超时时间（秒）"""

    # 重连配置
    enable_reconnect: bool = True
    """是否启用自动重连"""

    max_reconnect_attempts: int = 10
    """最大重连尝试次数，-1 表示无限重连"""

    initial_reconnect_delay: float = 1.0
    """初始重连延迟时间（秒）"""

    max_reconnect_delay: float = 60.0
    """最大重连延迟时间（秒）"""

    reconnect_backoff_factor: float = 2.0
    """重连延迟指数退避因子"""

    # 事件处理配置
    event_buffer_size: int = 1000
    """事件缓冲区大小"""

    enable_event_logging: bool = True
    """是否启用事件日志记录"""

    # 订阅配置
    subscribed_events: list[str] = field(default_factory=lambda: [])
    """订阅的事件类型列表，空列表表示订阅所有事件"""

    # 高级配置
    custom_headers: Dict[str, str] = field(default_factory=dict)
    """自定义 HTTP 头部"""

    user_agent: str = "MaiBot-MCP-SSE-Client/1.0"
    """用户代理字符串"""

    # SSL 配置
    verify_ssl: bool = True
    """是否验证 SSL 证书"""

    ssl_cert_path: Optional[str] = None
    """SSL 客户端证书路径"""

    ssl_key_path: Optional[str] = None
    """SSL 客户端密钥路径"""

    def __post_init__(self):
        """配置验证"""
        if self.enable and not self.server_url:
            raise ValueError("启用 MCP SSE 客户端时必须提供 server_url")
        
        if self.connection_timeout <= 0:
            raise ValueError("connection_timeout 必须大于 0")
        
        if self.read_timeout <= 0:
            raise ValueError("read_timeout 必须大于 0")
        
        if self.max_reconnect_attempts < -1:
            raise ValueError("max_reconnect_attempts 必须大于等于 -1")
        
        if self.initial_reconnect_delay <= 0:
            raise ValueError("initial_reconnect_delay 必须大于 0")
        
        if self.max_reconnect_delay <= 0:
            raise ValueError("max_reconnect_delay 必须大于 0")
        
        if self.reconnect_backoff_factor <= 1.0:
            raise ValueError("reconnect_backoff_factor 必须大于 1.0")
        
        if self.event_buffer_size <= 0:
            raise ValueError("event_buffer_size 必须大于 0")

    def get_headers(self) -> Dict[str, str]:
        """获取完整的 HTTP 头部"""
        headers = {
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
            "User-Agent": self.user_agent,
        }
        
        if self.auth_key:
            headers["Authorization"] = f"Bearer {self.auth_key}"
        
        headers.update(self.custom_headers)
        return headers