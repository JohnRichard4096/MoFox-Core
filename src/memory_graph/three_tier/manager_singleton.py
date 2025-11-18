"""
三层记忆系统单例管理器

提供全局访问点
"""

from pathlib import Path

from src.common.logger import get_logger
from src.config.config import global_config
from src.memory_graph.three_tier.unified_manager import UnifiedMemoryManager

logger = get_logger(__name__)

# 全局单例
_unified_memory_manager: UnifiedMemoryManager | None = None


async def initialize_unified_memory_manager() -> UnifiedMemoryManager:
    """
    初始化统一记忆管理器

    从全局配置读取参数

    Returns:
        初始化后的管理器实例
    """
    global _unified_memory_manager

    if _unified_memory_manager is not None:
        logger.warning("统一记忆管理器已经初始化")
        return _unified_memory_manager

    try:
        # 检查是否启用三层记忆系统
        if not hasattr(global_config, "three_tier_memory") or not getattr(
            global_config.three_tier_memory, "enable", False
        ):
            logger.warning("三层记忆系统未启用，跳过初始化")
            return None

        config = global_config.three_tier_memory

        # 创建管理器实例
        _unified_memory_manager = UnifiedMemoryManager(
            data_dir=Path(getattr(config, "data_dir", "data/memory_graph/three_tier")),
            # 感知记忆配置
            perceptual_max_blocks=getattr(config, "perceptual_max_blocks", 50),
            perceptual_block_size=getattr(config, "perceptual_block_size", 5),
            perceptual_activation_threshold=getattr(config, "perceptual_activation_threshold", 3),
            perceptual_recall_top_k=getattr(config, "perceptual_recall_top_k", 5),
            perceptual_recall_threshold=getattr(config, "perceptual_recall_threshold", 0.55),
            # 短期记忆配置
            short_term_max_memories=getattr(config, "short_term_max_memories", 30),
            short_term_transfer_threshold=getattr(config, "short_term_transfer_threshold", 0.6),
            # 长期记忆配置
            long_term_batch_size=getattr(config, "long_term_batch_size", 10),
            long_term_search_top_k=getattr(config, "long_term_search_top_k", 5),
            long_term_decay_factor=getattr(config, "long_term_decay_factor", 0.95),
            # 智能检索配置
            judge_confidence_threshold=getattr(config, "judge_confidence_threshold", 0.7),
        )

        # 初始化
        await _unified_memory_manager.initialize()

        logger.info("✅ 统一记忆管理器单例已初始化")
        return _unified_memory_manager

    except Exception as e:
        logger.error(f"初始化统一记忆管理器失败: {e}", exc_info=True)
        raise


def get_unified_memory_manager() -> UnifiedMemoryManager | None:
    """
    获取统一记忆管理器实例

    Returns:
        管理器实例，未初始化返回 None
    """
    if _unified_memory_manager is None:
        logger.warning("统一记忆管理器尚未初始化，请先调用 initialize_unified_memory_manager()")
    return _unified_memory_manager


async def shutdown_unified_memory_manager() -> None:
    """关闭统一记忆管理器"""
    global _unified_memory_manager

    if _unified_memory_manager is None:
        logger.warning("统一记忆管理器未初始化，无需关闭")
        return

    try:
        await _unified_memory_manager.shutdown()
        _unified_memory_manager = None
        logger.info("✅ 统一记忆管理器已关闭")

    except Exception as e:
        logger.error(f"关闭统一记忆管理器失败: {e}", exc_info=True)
