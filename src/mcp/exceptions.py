"""
MCP SSE 客户端异常类
"""


class MCPError(Exception):
    """MCP 基础异常类"""
    pass


class MCPConnectionError(MCPError):
    """MCP 连接异常"""
    
    def __init__(self, message: str, url: str = None, status_code: int = None):
        super().__init__(message)
        self.url = url
        self.status_code = status_code
    
    def __str__(self):
        base_msg = super().__str__()
        if self.url:
            base_msg += f" (URL: {self.url})"
        if self.status_code:
            base_msg += f" (Status: {self.status_code})"
        return base_msg


class MCPEventError(MCPError):
    """MCP 事件处理异常"""
    
    def __init__(self, message: str, event_type: str = None, event_data: str = None):
        super().__init__(message)
        self.event_type = event_type
        self.event_data = event_data
    
    def __str__(self):
        base_msg = super().__str__()
        if self.event_type:
            base_msg += f" (Event Type: {self.event_type})"
        return base_msg


class MCPAuthenticationError(MCPConnectionError):
    """MCP 认证异常"""
    pass


class MCPTimeoutError(MCPConnectionError):
    """MCP 超时异常"""
    pass


class MCPReconnectError(MCPConnectionError):
    """MCP 重连异常"""
    
    def __init__(self, message: str, attempts: int = 0, max_attempts: int = 0):
        super().__init__(message)
        self.attempts = attempts
        self.max_attempts = max_attempts
    
    def __str__(self):
        base_msg = super().__str__()
        if self.max_attempts > 0:
            base_msg += f" (Attempts: {self.attempts}/{self.max_attempts})"
        else:
            base_msg += f" (Attempts: {self.attempts})"
        return base_msg