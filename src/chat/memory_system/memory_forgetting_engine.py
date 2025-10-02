"""
智能记忆遗忘引擎
基于重要程度、置信度和激活频率的智能遗忘机制
"""

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime

from src.chat.memory_system.memory_chunk import ConfidenceLevel, ImportanceLevel, MemoryChunk
from src.common.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ForgettingStats:
    """遗忘统计信息"""

    total_checked: int = 0
    marked_for_forgetting: int = 0
    actually_forgotten: int = 0
    dormant_memories: int = 0
    last_check_time: float = 0.0
    check_duration: float = 0.0


@dataclass
class ForgettingConfig:
    """遗忘引擎配置"""

    # 检查频率配置
    check_interval_hours: int = 24  # 定期检查间隔（小时）
    batch_size: int = 100  # 批处理大小

    # 遗忘阈值配置
    base_forgetting_days: float = 30.0  # 基础遗忘天数
    min_forgetting_days: float = 7.0  # 最小遗忘天数
    max_forgetting_days: float = 365.0  # 最大遗忘天数

    # 重要程度权重
    critical_importance_bonus: float = 45.0  # 关键重要性额外天数
    high_importance_bonus: float = 30.0  # 高重要性额外天数
    normal_importance_bonus: float = 15.0  # 一般重要性额外天数
    low_importance_bonus: float = 0.0  # 低重要性额外天数

    # 置信度权重
    verified_confidence_bonus: float = 30.0  # 已验证置信度额外天数
    high_confidence_bonus: float = 20.0  # 高置信度额外天数
    medium_confidence_bonus: float = 10.0  # 中等置信度额外天数
    low_confidence_bonus: float = 0.0  # 低置信度额外天数

    # 激活频率权重
    activation_frequency_weight: float = 0.5  # 每次激活增加的天数权重
    max_frequency_bonus: float = 10.0  # 最大激活频率奖励天数

    # 休眠配置
    dormant_threshold_days: int = 90  # 休眠状态判定天数
    force_forget_dormant_days: int = 180  # 强制遗忘休眠记忆的天数


class MemoryForgettingEngine:
    """智能记忆遗忘引擎"""

    def __init__(self, config: ForgettingConfig | None = None):
        self.config = config or ForgettingConfig()
        self.stats = ForgettingStats()
        self._last_forgetting_check = 0.0
        self._forgetting_lock = asyncio.Lock()

        logger.info("MemoryForgettingEngine 初始化完成")

    def calculate_forgetting_threshold(self, memory: MemoryChunk) -> float:
        """
        计算记忆的遗忘阈值（天数）

        Args:
            memory: 记忆块

        Returns:
            遗忘阈值（天数）
        """
        # 基础天数
        threshold = self.config.base_forgetting_days

        # 重要性权重
        importance = memory.metadata.importance
        if importance == ImportanceLevel.CRITICAL:
            threshold += self.config.critical_importance_bonus
        elif importance == ImportanceLevel.HIGH:
            threshold += self.config.high_importance_bonus
        elif importance == ImportanceLevel.NORMAL:
            threshold += self.config.normal_importance_bonus
        # LOW 级别不增加额外天数

        # 置信度权重
        confidence = memory.metadata.confidence
        if confidence == ConfidenceLevel.VERIFIED:
            threshold += self.config.verified_confidence_bonus
        elif confidence == ConfidenceLevel.HIGH:
            threshold += self.config.high_confidence_bonus
        elif confidence == ConfidenceLevel.MEDIUM:
            threshold += self.config.medium_confidence_bonus
        # LOW 级别不增加额外天数

        # 激活频率权重
        frequency_bonus = min(
            memory.metadata.activation_frequency * self.config.activation_frequency_weight,
            self.config.max_frequency_bonus,
        )
        threshold += frequency_bonus

        # 确保在合理范围内
        return max(self.config.min_forgetting_days, min(threshold, self.config.max_forgetting_days))

    def should_forget_memory(self, memory: MemoryChunk, current_time: float | None = None) -> bool:
        """
        判断记忆是否应该被遗忘

        Args:
            memory: 记忆块
            current_time: 当前时间戳

        Returns:
            是否应该遗忘
        """
        if current_time is None:
            current_time = time.time()

        # 关键重要性的记忆永不遗忘
        if memory.metadata.importance == ImportanceLevel.CRITICAL:
            return False

        # 计算遗忘阈值
        forgetting_threshold = self.calculate_forgetting_threshold(memory)

        # 计算距离最后激活的时间
        days_since_activation = (current_time - memory.metadata.last_activation_time) / 86400

        # 判断是否超过阈值
        should_forget = days_since_activation > forgetting_threshold

        if should_forget:
            logger.debug(
                f"记忆 {memory.memory_id[:8]} 触发遗忘条件: "
                f"重要性={memory.metadata.importance.name}, "
                f"置信度={memory.metadata.confidence.name}, "
                f"激活频率={memory.metadata.activation_frequency}, "
                f"阈值={forgetting_threshold:.1f}天, "
                f"未激活天数={days_since_activation:.1f}天"
            )

        return should_forget

    def is_dormant_memory(self, memory: MemoryChunk, current_time: float | None = None) -> bool:
        """
        判断记忆是否处于休眠状态

        Args:
            memory: 记忆块
            current_time: 当前时间戳

        Returns:
            是否处于休眠状态
        """
        return memory.is_dormant(current_time, self.config.dormant_threshold_days)

    def should_force_forget_dormant(self, memory: MemoryChunk, current_time: float | None = None) -> bool:
        """
        判断是否应该强制遗忘休眠记忆

        Args:
            memory: 记忆块
            current_time: 当前时间戳

        Returns:
            是否应该强制遗忘
        """
        if current_time is None:
            current_time = time.time()

        # 只有非关键重要性的记忆才会被强制遗忘
        if memory.metadata.importance == ImportanceLevel.CRITICAL:
            return False

        days_since_last_access = (current_time - memory.metadata.last_accessed) / 86400
        return days_since_last_access > self.config.force_forget_dormant_days

    async def check_memories_for_forgetting(self, memories: list[MemoryChunk]) -> tuple[list[str], list[str]]:
        """
        检查记忆列表，识别需要遗忘的记忆

        Args:
            memories: 记忆块列表

        Returns:
            (普通遗忘列表, 强制遗忘列表)
        """
        start_time = time.time()
        current_time = start_time

        normal_forgetting_ids = []
        force_forgetting_ids = []

        self.stats.total_checked = len(memories)
        self.stats.last_check_time = current_time

        for memory in memories:
            try:
                # 检查休眠状态
                if self.is_dormant_memory(memory, current_time):
                    self.stats.dormant_memories += 1

                    # 检查是否应该强制遗忘休眠记忆
                    if self.should_force_forget_dormant(memory, current_time):
                        force_forgetting_ids.append(memory.memory_id)
                        logger.debug(f"休眠记忆 {memory.memory_id[:8]} 被标记为强制遗忘")
                        continue

                # 检查普通遗忘条件
                if self.should_forget_memory(memory, current_time):
                    normal_forgetting_ids.append(memory.memory_id)
                    self.stats.marked_for_forgetting += 1

            except Exception as e:
                logger.warning(f"检查记忆 {memory.memory_id[:8]} 遗忘状态失败: {e}")
                continue

        self.stats.check_duration = time.time() - start_time

        logger.info(
            f"遗忘检查完成 | 总数={self.stats.total_checked}, "
            f"标记遗忘={len(normal_forgetting_ids)}, "
            f"强制遗忘={len(force_forgetting_ids)}, "
            f"休眠={self.stats.dormant_memories}, "
            f"耗时={self.stats.check_duration:.3f}s"
        )

        return normal_forgetting_ids, force_forgetting_ids

    async def perform_forgetting_check(self, memories: list[MemoryChunk]) -> dict[str, any]:
        """
        执行完整的遗忘检查流程

        Args:
            memories: 记忆块列表

        Returns:
            检查结果统计
        """
        async with self._forgetting_lock:
            normal_forgetting, force_forgetting = await self.check_memories_for_forgetting(memories)

            # 更新统计
            self.stats.actually_forgotten = len(normal_forgetting) + len(force_forgetting)

            return {
                "normal_forgetting": normal_forgetting,
                "force_forgetting": force_forgetting,
                "stats": {
                    "total_checked": self.stats.total_checked,
                    "marked_for_forgetting": self.stats.marked_for_forgetting,
                    "actually_forgotten": self.stats.actually_forgotten,
                    "dormant_memories": self.stats.dormant_memories,
                    "check_duration": self.stats.check_duration,
                    "last_check_time": self.stats.last_check_time,
                },
            }

    def is_forgetting_check_needed(self) -> bool:
        """检查是否需要进行遗忘检查"""
        current_time = time.time()
        hours_since_last_check = (current_time - self._last_forgetting_check) / 3600

        return hours_since_last_check >= self.config.check_interval_hours

    async def schedule_periodic_check(self, memories_provider, enable_auto_cleanup: bool = True):
        """
        定期执行遗忘检查（可以在后台任务中调用）

        Args:
            memories_provider: 提供记忆列表的函数
            enable_auto_cleanup: 是否启用自动清理
        """
        if not self.is_forgetting_check_needed():
            return

        try:
            logger.info("开始执行定期遗忘检查...")

            # 获取记忆列表
            memories = await memories_provider()

            if not memories:
                logger.debug("无记忆数据需要检查")
                return

            # 执行遗忘检查
            result = await self.perform_forgetting_check(memories)

            # 如果启用自动清理，执行实际的遗忘操作
            if enable_auto_cleanup and (result["normal_forgetting"] or result["force_forgetting"]):
                logger.info(
                    f"检测到 {len(result['normal_forgetting'])} 条普通遗忘和 {len(result['force_forgetting'])} 条强制遗忘记忆"
                )
                # 这里可以调用实际的删除逻辑
                # await self.cleanup_forgotten_memories(result["normal_forgetting"] + result["force_forgetting"])

            self._last_forgetting_check = time.time()

        except Exception as e:
            logger.error(f"定期遗忘检查失败: {e}", exc_info=True)

    def get_forgetting_stats(self) -> dict[str, any]:
        """获取遗忘统计信息"""
        return {
            "total_checked": self.stats.total_checked,
            "marked_for_forgetting": self.stats.marked_for_forgetting,
            "actually_forgotten": self.stats.actually_forgotten,
            "dormant_memories": self.stats.dormant_memories,
            "last_check_time": datetime.fromtimestamp(self.stats.last_check_time).isoformat()
            if self.stats.last_check_time
            else None,
            "last_check_duration": self.stats.check_duration,
            "config": {
                "check_interval_hours": self.config.check_interval_hours,
                "base_forgetting_days": self.config.base_forgetting_days,
                "min_forgetting_days": self.config.min_forgetting_days,
                "max_forgetting_days": self.config.max_forgetting_days,
            },
        }

    def reset_stats(self):
        """重置统计信息"""
        self.stats = ForgettingStats()
        logger.debug("遗忘统计信息已重置")

    def update_config(self, **kwargs):
        """更新配置"""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
                logger.debug(f"遗忘配置更新: {key} = {value}")
            else:
                logger.warning(f"未知的配置项: {key}")


# 创建全局遗忘引擎实例
memory_forgetting_engine = MemoryForgettingEngine()


def get_memory_forgetting_engine() -> MemoryForgettingEngine:
    """获取全局遗忘引擎实例"""
    return memory_forgetting_engine
