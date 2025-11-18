"""
三层记忆系统 (Three-Tier Memory System)

分层架构：
1. 感知记忆层 (Perceptual Memory Layer) - 消息块的短期缓存
2. 短期记忆层 (Short-term Memory Layer) - 结构化的活跃记忆
3. 长期记忆层 (Long-term Memory Layer) - 持久化的图结构记忆

设计灵感来源于人脑的记忆机制和 Mem0 项目。
"""

from .models import (
    MemoryBlock,
    PerceptualMemory,
    ShortTermMemory,
    GraphOperation,
    GraphOperationType,
    JudgeDecision,
)
from .perceptual_manager import PerceptualMemoryManager
from .short_term_manager import ShortTermMemoryManager
from .long_term_manager import LongTermMemoryManager
from .unified_manager import UnifiedMemoryManager

__all__ = [
    # 数据模型
    "MemoryBlock",
    "PerceptualMemory",
    "ShortTermMemory",
    "GraphOperation",
    "GraphOperationType",
    "JudgeDecision",
    # 管理器
    "PerceptualMemoryManager",
    "ShortTermMemoryManager",
    "LongTermMemoryManager",
    "UnifiedMemoryManager",
]
