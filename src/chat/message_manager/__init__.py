"""
消息管理器模块
提供统一的消息管理、上下文管理和流循环调度功能

基于 Generator + Tick 的事件驱动模式
"""

from .distribution_manager import (
    ConversationTick,
    StreamLoopManager,
    conversation_loop,
    run_chat_stream,
    stream_loop_manager,
)
from .message_manager import MessageManager, message_manager

__all__ = [
    "ConversationTick",
    "MessageManager",
    "StreamLoopManager",
    "conversation_loop",
    "message_manager",
    "run_chat_stream",
    "stream_loop_manager",
]
