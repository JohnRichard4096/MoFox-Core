"""
简化记忆系统模块
移除即时记忆和长期记忆分类，实现统一记忆架构和智能遗忘机制
"""

# 核心数据结构
# 激活器
from .enhanced_memory_activator import MemoryActivator, enhanced_memory_activator, memory_activator
from .memory_chunk import (
    ConfidenceLevel,
    ContentStructure,
    ImportanceLevel,
    MemoryChunk,
    MemoryMetadata,
    MemoryType,
    create_memory_chunk,
)

# 兼容性别名
from .memory_chunk import MemoryChunk as Memory

# 遗忘引擎
from .memory_forgetting_engine import ForgettingConfig, MemoryForgettingEngine, get_memory_forgetting_engine

# 记忆管理器
from .memory_manager import MemoryManager, MemoryResult, memory_manager

# 记忆核心系统
from .memory_system import MemorySystem, MemorySystemConfig, get_memory_system, initialize_memory_system

# Vector DB存储系统
from .vector_memory_storage_v2 import VectorMemoryStorage, VectorStorageConfig, get_vector_memory_storage

__all__ = [
    # 核心数据结构
    "MemoryChunk",
    "Memory",  # 兼容性别名
    "MemoryMetadata",
    "ContentStructure",
    "MemoryType",
    "ImportanceLevel",
    "ConfidenceLevel",
    "create_memory_chunk",
    # 遗忘引擎
    "MemoryForgettingEngine",
    "ForgettingConfig",
    "get_memory_forgetting_engine",
    # Vector DB存储
    "VectorMemoryStorage",
    "VectorStorageConfig",
    "get_vector_memory_storage",
    # 记忆系统
    "MemorySystem",
    "MemorySystemConfig",
    "get_memory_system",
    "initialize_memory_system",
    # 记忆管理器
    "MemoryManager",
    "MemoryResult",
    "memory_manager",
    # 激活器
    "MemoryActivator",
    "memory_activator",
    "enhanced_memory_activator",  # 兼容性别名
]

# 版本信息
__version__ = "3.0.0"
__author__ = "MoFox Team"
__description__ = "简化记忆系统 - 统一记忆架构与智能遗忘机制"
