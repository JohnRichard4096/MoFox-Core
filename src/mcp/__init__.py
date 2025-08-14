"""
MCP (Model Context Protocol) 模块

提供 MCP 服务器的 Server-Sent Events (SSE) 客户端功能，
支持实时事件订阅、断线重连和事件处理。
"""

from .sse_client import MCPSSEClient
from .event_handler import MCPEventHandler, MCPEvent
from .exceptions import MCPConnectionError, MCPEventError
from .manager import (
    MCPSSEManager,
    get_mcp_sse_manager,
    initialize_mcp_sse_manager,
    start_mcp_sse_manager,
    stop_mcp_sse_manager,
)
from .config import MCPSSEConfig

__all__ = [
    "MCPSSEClient",
    "MCPEventHandler",
    "MCPEvent",
    "MCPConnectionError",
    "MCPEventError",
    "MCPSSEManager",
    "MCPSSEConfig",
    "get_mcp_sse_manager",
    "initialize_mcp_sse_manager",
    "start_mcp_sse_manager",
    "stop_mcp_sse_manager",
]