"""
增强重排序器
实现文档设计的多维度评分模型
"""

import math
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.chat.memory_system.memory_chunk import MemoryChunk, MemoryType
from src.common.logger import get_logger

logger = get_logger(__name__)


class IntentType(Enum):
    """对话意图类型"""

    FACT_QUERY = "fact_query"  # 事实查询
    EVENT_RECALL = "event_recall"  # 事件回忆
    PREFERENCE_CHECK = "preference_check"  # 偏好检查
    GENERAL_CHAT = "general_chat"  # 一般对话
    UNKNOWN = "unknown"  # 未知意图


@dataclass
class ReRankingConfig:
    """重排序配置"""

    # 权重配置 (w1 + w2 + w3 + w4 = 1.0)
    semantic_weight: float = 0.5  # 语义相似度权重
    recency_weight: float = 0.2  # 时效性权重
    usage_freq_weight: float = 0.2  # 使用频率权重
    type_match_weight: float = 0.1  # 类型匹配权重

    # 时效性衰减参数
    recency_decay_rate: float = 0.1  # 时效性衰减率 (天)

    # 使用频率计算参数
    freq_log_base: float = 2.0  # 对数底数
    freq_max_score: float = 5.0  # 最大频率得分

    # 类型匹配权重映射
    type_match_weights: dict[str, dict[str, float]] = None

    def __post_init__(self):
        """初始化类型匹配权重"""
        if self.type_match_weights is None:
            self.type_match_weights = {
                IntentType.FACT_QUERY.value: {
                    MemoryType.PERSONAL_FACT.value: 1.0,
                    MemoryType.KNOWLEDGE.value: 0.8,
                    MemoryType.PREFERENCE.value: 0.5,
                    MemoryType.EVENT.value: 0.3,
                    "default": 0.3,
                },
                IntentType.EVENT_RECALL.value: {
                    MemoryType.EVENT.value: 1.0,
                    MemoryType.EXPERIENCE.value: 0.8,
                    MemoryType.EMOTION.value: 0.6,
                    MemoryType.PERSONAL_FACT.value: 0.5,
                    "default": 0.5,
                },
                IntentType.PREFERENCE_CHECK.value: {
                    MemoryType.PREFERENCE.value: 1.0,
                    MemoryType.OPINION.value: 0.8,
                    MemoryType.GOAL.value: 0.6,
                    MemoryType.PERSONAL_FACT.value: 0.4,
                    "default": 0.4,
                },
                IntentType.GENERAL_CHAT.value: {"default": 0.8},
                IntentType.UNKNOWN.value: {"default": 0.8},
            }


class IntentClassifier:
    """轻量级意图识别器"""

    def __init__(self):
        # 关键词模式匹配规则
        self.patterns = {
            IntentType.FACT_QUERY: [
                # 中文模式
                "我是",
                "我的",
                "我叫",
                "我在",
                "我住在",
                "我的职业",
                "我的工作",
                "什么时候",
                "在哪里",
                "是什么",
                "多少",
                "几岁",
                "年龄",
                # 英文模式
                "what is",
                "where is",
                "when is",
                "how old",
                "my name",
                "i am",
                "i live",
            ],
            IntentType.EVENT_RECALL: [
                # 中文模式
                "记得",
                "想起",
                "还记得",
                "那次",
                "上次",
                "之前",
                "以前",
                "曾经",
                "发生过",
                "经历",
                "做过",
                "去过",
                "见过",
                # 英文模式
                "remember",
                "recall",
                "last time",
                "before",
                "previously",
                "happened",
                "experience",
            ],
            IntentType.PREFERENCE_CHECK: [
                # 中文模式
                "喜欢",
                "不喜欢",
                "偏好",
                "爱好",
                "兴趣",
                "讨厌",
                "最爱",
                "最喜欢",
                "习惯",
                "通常",
                "一般",
                "倾向于",
                "更喜欢",
                # 英文模式
                "like",
                "love",
                "hate",
                "prefer",
                "favorite",
                "usually",
                "tend to",
                "interest",
            ],
        }

    def classify_intent(self, query: str, context: dict[str, Any]) -> IntentType:
        """识别对话意图"""
        if not query:
            return IntentType.UNKNOWN

        query_lower = query.lower()

        # 统计各意图的匹配分数
        intent_scores = dict.fromkeys(IntentType, 0)

        for intent, patterns in self.patterns.items():
            for pattern in patterns:
                if pattern in query_lower:
                    intent_scores[intent] += 1

        # 返回得分最高的意图
        max_score = max(intent_scores.values())
        if max_score == 0:
            return IntentType.GENERAL_CHAT

        for intent, score in intent_scores.items():
            if score == max_score:
                return intent

        return IntentType.GENERAL_CHAT


class EnhancedReRanker:
    """增强重排序器 - 实现文档设计的多维度评分模型"""

    def __init__(self, config: ReRankingConfig | None = None):
        self.config = config or ReRankingConfig()
        self.intent_classifier = IntentClassifier()

        # 验证权重和为1.0
        total_weight = (
            self.config.semantic_weight
            + self.config.recency_weight
            + self.config.usage_freq_weight
            + self.config.type_match_weight
        )

        if abs(total_weight - 1.0) > 0.01:
            logger.warning(f"重排序权重和不为1.0: {total_weight}, 将进行归一化")
            # 归一化权重
            self.config.semantic_weight /= total_weight
            self.config.recency_weight /= total_weight
            self.config.usage_freq_weight /= total_weight
            self.config.type_match_weight /= total_weight

    def rerank_memories(
        self,
        query: str,
        candidate_memories: list[tuple[str, MemoryChunk, float]],  # (memory_id, memory, vector_similarity)
        context: dict[str, Any],
        limit: int = 10,
    ) -> list[tuple[str, MemoryChunk, float]]:
        """
        对候选记忆进行重排序

        Args:
            query: 查询文本
            candidate_memories: 候选记忆列表 [(memory_id, memory, vector_similarity)]
            context: 上下文信息
            limit: 返回数量限制

        Returns:
            重排序后的记忆列表 [(memory_id, memory, final_score)]
        """
        if not candidate_memories:
            return []

        # 识别查询意图
        intent = self.intent_classifier.classify_intent(query, context)
        logger.debug(f"识别到查询意图: {intent.value}")

        # 计算每个候选记忆的最终得分
        scored_memories = []
        current_time = time.time()

        for memory_id, memory, vector_sim in candidate_memories:
            try:
                # 1. 语义相似度得分 (已归一化到[0,1])
                semantic_score = self._normalize_similarity(vector_sim)

                # 2. 时效性得分
                recency_score = self._calculate_recency_score(memory, current_time)

                # 3. 使用频率得分
                usage_freq_score = self._calculate_usage_frequency_score(memory)

                # 4. 类型匹配得分
                type_match_score = self._calculate_type_match_score(memory, intent)

                # 计算最终得分
                final_score = (
                    self.config.semantic_weight * semantic_score
                    + self.config.recency_weight * recency_score
                    + self.config.usage_freq_weight * usage_freq_score
                    + self.config.type_match_weight * type_match_score
                )

                scored_memories.append((memory_id, memory, final_score))

                # 记录调试信息
                logger.debug(
                    f"记忆评分 {memory_id[:8]}: semantic={semantic_score:.3f}, "
                    f"recency={recency_score:.3f}, freq={usage_freq_score:.3f}, "
                    f"type={type_match_score:.3f}, final={final_score:.3f}"
                )

            except Exception as e:
                logger.error(f"计算记忆 {memory_id} 得分时出错: {e}")
                # 使用向量相似度作为后备得分
                scored_memories.append((memory_id, memory, vector_sim))

        # 按最终得分降序排序
        scored_memories.sort(key=lambda x: x[2], reverse=True)

        # 返回前N个结果
        result = scored_memories[:limit]

        highest_score = result[0][2] if result else 0.0
        logger.info(
            f"重排序完成: 候选={len(candidate_memories)}, 返回={len(result)}, "
            f"意图={intent.value}, 最高分={highest_score:.3f}"
        )

        return result

    def _normalize_similarity(self, raw_similarity: float) -> float:
        """归一化相似度到[0,1]区间"""
        # 假设原始相似度已经在[-1,1]或[0,1]区间
        if raw_similarity < 0:
            return (raw_similarity + 1) / 2  # 从[-1,1]映射到[0,1]
        return min(1.0, max(0.0, raw_similarity))  # 确保在[0,1]区间

    def _calculate_recency_score(self, memory: MemoryChunk, current_time: float) -> float:
        """
        计算时效性得分
        公式: Recency = 1 / (1 + decay_rate * days_old)
        """
        last_accessed = memory.metadata.last_accessed or memory.metadata.created_at
        days_old = (current_time - last_accessed) / (24 * 3600)  # 转换为天数

        if days_old < 0:
            days_old = 0  # 处理时间异常

        score = 1 / (1 + self.config.recency_decay_rate * days_old)
        return min(1.0, max(0.0, score))

    def _calculate_usage_frequency_score(self, memory: MemoryChunk) -> float:
        """
        计算使用频率得分
        公式: Usage_Freq = min(1.0, log2(access_count + 1) / max_score)
        """
        access_count = memory.metadata.access_count
        if access_count <= 0:
            return 0.0

        log_count = math.log2(access_count + 1)
        score = log_count / self.config.freq_max_score
        return min(1.0, max(0.0, score))

    def _calculate_type_match_score(self, memory: MemoryChunk, intent: IntentType) -> float:
        """计算类型匹配得分"""
        memory_type = memory.memory_type.value
        intent_value = intent.value

        # 获取对应意图的类型权重映射
        type_weights = self.config.type_match_weights.get(intent_value, {})

        # 查找具体类型的权重，如果没有则使用默认权重
        score = type_weights.get(memory_type, type_weights.get("default", 0.8))

        return min(1.0, max(0.0, score))


# 创建默认的重排序器实例
default_reranker = EnhancedReRanker()


def rerank_candidate_memories(
    query: str,
    candidate_memories: list[tuple[str, MemoryChunk, float]],
    context: dict[str, Any],
    limit: int = 10,
    config: ReRankingConfig | None = None,
) -> list[tuple[str, MemoryChunk, float]]:
    """
    便捷函数：对候选记忆进行重排序
    """
    if config:
        reranker = EnhancedReRanker(config)
    else:
        reranker = default_reranker

    return reranker.rerank_memories(query, candidate_memories, context, limit)
