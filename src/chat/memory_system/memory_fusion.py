"""
记忆融合与去重机制
避免记忆碎片化，确保长期记忆库的高质量
"""

import time
from dataclasses import dataclass
from typing import Any

from src.chat.memory_system.memory_chunk import ConfidenceLevel, ImportanceLevel, MemoryChunk
from src.common.logger import get_logger

logger = get_logger(__name__)


@dataclass
class FusionResult:
    """融合结果"""

    original_count: int
    fused_count: int
    removed_duplicates: int
    merged_memories: list[MemoryChunk]
    fusion_time: float
    details: list[str]


@dataclass
class DuplicateGroup:
    """重复记忆组"""

    group_id: str
    memories: list[MemoryChunk]
    similarity_matrix: list[list[float]]
    representative_memory: MemoryChunk | None = None


class MemoryFusionEngine:
    """记忆融合引擎"""

    def __init__(self, similarity_threshold: float = 0.85):
        self.similarity_threshold = similarity_threshold
        self.fusion_stats = {
            "total_fusions": 0,
            "memories_fused": 0,
            "duplicates_removed": 0,
            "average_similarity": 0.0,
        }

        # 融合策略配置
        self.fusion_strategies = {
            "semantic_similarity": True,  # 语义相似性融合
            "temporal_proximity": True,  # 时间接近性融合
            "logical_consistency": True,  # 逻辑一致性融合
            "confidence_boosting": True,  # 置信度提升
            "importance_preservation": True,  # 重要性保持
        }

    async def fuse_memories(
        self, new_memories: list[MemoryChunk], existing_memories: list[MemoryChunk] | None = None
    ) -> list[MemoryChunk]:
        """融合记忆列表"""
        start_time = time.time()

        try:
            if not new_memories:
                return []

            logger.info(f"开始记忆融合，新记忆: {len(new_memories)}，现有记忆: {len(existing_memories or [])}")

            # 1. 检测重复记忆组
            duplicate_groups = await self._detect_duplicate_groups(new_memories, existing_memories or [])

            if not duplicate_groups:
                fusion_time = time.time() - start_time
                self._update_fusion_stats(len(new_memories), 0, fusion_time)
                logger.info("✅ 记忆融合完成: %d 条记忆，移除 0 条重复", len(new_memories))
                return new_memories

            # 2. 对每个重复组进行融合
            fused_memories = []
            removed_count = 0

            for group in duplicate_groups:
                if len(group.memories) == 1:
                    # 单个记忆，直接添加
                    fused_memories.append(group.memories[0])
                else:
                    # 多个记忆，进行融合
                    fused_memory = await self._fuse_memory_group(group)
                    if fused_memory:
                        fused_memories.append(fused_memory)
                        removed_count += len(group.memories) - 1

            # 3. 更新统计
            fusion_time = time.time() - start_time
            self._update_fusion_stats(len(new_memories), removed_count, fusion_time)

            logger.info(f"✅ 记忆融合完成: {len(fused_memories)} 条记忆，移除 {removed_count} 条重复")
            return fused_memories

        except Exception as e:
            logger.error(f"❌ 记忆融合失败: {e}", exc_info=True)
            return new_memories  # 失败时返回原始记忆

    async def _detect_duplicate_groups(
        self, new_memories: list[MemoryChunk], existing_memories: list[MemoryChunk]
    ) -> list[DuplicateGroup]:
        """检测重复记忆组"""
        all_memories = new_memories + existing_memories
        new_memory_ids = {memory.memory_id for memory in new_memories}
        groups = []
        processed_ids = set()

        for i, memory1 in enumerate(all_memories):
            if memory1.memory_id in processed_ids:
                continue

            # 创建新的重复组
            group = DuplicateGroup(group_id=f"group_{len(groups)}", memories=[memory1], similarity_matrix=[[1.0]])

            processed_ids.add(memory1.memory_id)

            # 寻找相似记忆
            for j, memory2 in enumerate(all_memories[i + 1 :], i + 1):
                if memory2.memory_id in processed_ids:
                    continue

                similarity = self._calculate_comprehensive_similarity(memory1, memory2)

                if similarity >= self.similarity_threshold:
                    group.memories.append(memory2)
                    processed_ids.add(memory2.memory_id)

                    # 更新相似度矩阵
                    self._update_similarity_matrix(group, memory2, similarity)

            if len(group.memories) > 1:
                # 选择代表性记忆
                group.representative_memory = self._select_representative_memory(group)
                groups.append(group)
            else:
                # 仅包含单条记忆，只有当其来自新记忆列表时保留
                if memory1.memory_id in new_memory_ids:
                    groups.append(group)

        logger.debug(f"检测到 {len(groups)} 个重复记忆组")
        return groups

    def _calculate_comprehensive_similarity(self, mem1: MemoryChunk, mem2: MemoryChunk) -> float:
        """计算综合相似度"""
        similarity_scores = []

        # 1. 语义向量相似度
        if self.fusion_strategies["semantic_similarity"]:
            semantic_sim = mem1.calculate_similarity(mem2)
            similarity_scores.append(("semantic", semantic_sim))

        # 2. 文本相似度
        text_sim = self._calculate_text_similarity(mem1.text_content, mem2.text_content)
        similarity_scores.append(("text", text_sim))

        # 3. 关键词重叠度
        keyword_sim = self._calculate_keyword_similarity(mem1.keywords, mem2.keywords)
        similarity_scores.append(("keyword", keyword_sim))

        # 4. 类型一致性
        type_consistency = 1.0 if mem1.memory_type == mem2.memory_type else 0.0
        similarity_scores.append(("type", type_consistency))

        # 5. 时间接近性
        if self.fusion_strategies["temporal_proximity"]:
            temporal_sim = self._calculate_temporal_similarity(mem1.metadata.created_at, mem2.metadata.created_at)
            similarity_scores.append(("temporal", temporal_sim))

        # 6. 逻辑一致性
        if self.fusion_strategies["logical_consistency"]:
            logical_sim = self._calculate_logical_similarity(mem1, mem2)
            similarity_scores.append(("logical", logical_sim))

        # 计算加权平均相似度
        weights = {"semantic": 0.35, "text": 0.25, "keyword": 0.15, "type": 0.10, "temporal": 0.10, "logical": 0.05}

        weighted_sum = 0.0
        total_weight = 0.0

        for score_type, score in similarity_scores:
            weight = weights.get(score_type, 0.1)
            weighted_sum += weight * score
            total_weight += weight

        final_similarity = weighted_sum / total_weight if total_weight > 0 else 0.0

        logger.debug(f"综合相似度计算: {final_similarity:.3f} - {[(t, f'{s:.3f}') for t, s in similarity_scores]}")

        return final_similarity

    def _calculate_text_similarity(self, text1: str, text2: str) -> float:
        """计算文本相似度"""
        # 简单的词汇重叠度计算
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2

        jaccard_similarity = len(intersection) / len(union)
        return jaccard_similarity

    def _calculate_keyword_similarity(self, keywords1: list[str], keywords2: list[str]) -> float:
        """计算关键词相似度"""
        if not keywords1 or not keywords2:
            return 0.0

        set1 = set(k.lower() for k in keywords1)
        set2 = set(k.lower() for k in keywords2)

        intersection = set1 & set2
        union = set1 | set2

        return len(intersection) / len(union) if union else 0.0

    def _calculate_temporal_similarity(self, time1: float, time2: float) -> float:
        """计算时间相似度"""
        time_diff = abs(time1 - time2)
        hours_diff = time_diff / 3600

        # 24小时内相似度较高
        if hours_diff <= 24:
            return 1.0 - (hours_diff / 24)
        elif hours_diff <= 168:  # 一周内
            return 0.7 - ((hours_diff - 24) / 168) * 0.5
        else:
            return 0.2

    def _calculate_logical_similarity(self, mem1: MemoryChunk, mem2: MemoryChunk) -> float:
        """计算逻辑一致性"""
        # 检查主谓宾结构的逻辑一致性
        consistency_score = 0.0

        # 主语一致性
        subjects1 = set(mem1.subjects)
        subjects2 = set(mem2.subjects)
        if subjects1 or subjects2:
            overlap = len(subjects1 & subjects2)
            union_count = max(len(subjects1 | subjects2), 1)
            consistency_score += (overlap / union_count) * 0.4

        # 谓语相似性
        predicate_sim = self._calculate_text_similarity(mem1.content.predicate, mem2.content.predicate)
        consistency_score += predicate_sim * 0.3

        # 宾语相似性
        if isinstance(mem1.content.object, str) and isinstance(mem2.content.object, str):
            object_sim = self._calculate_text_similarity(str(mem1.content.object), str(mem2.content.object))
            consistency_score += object_sim * 0.3

        return consistency_score

    def _update_similarity_matrix(self, group: DuplicateGroup, new_memory: MemoryChunk, similarity: float):
        """更新组的相似度矩阵"""
        # 为新记忆添加行和列
        for i in range(len(group.similarity_matrix)):
            group.similarity_matrix[i].append(similarity)

        # 添加新行
        new_row = [similarity] + [1.0] * len(group.similarity_matrix)
        group.similarity_matrix.append(new_row)

    def _select_representative_memory(self, group: DuplicateGroup) -> MemoryChunk:
        """选择代表性记忆"""
        if not group.memories:
            return None

        # 评分标准
        best_memory = None
        best_score = -1.0

        for memory in group.memories:
            score = 0.0

            # 置信度权重
            score += memory.metadata.confidence.value * 0.3

            # 重要性权重
            score += memory.metadata.importance.value * 0.3

            # 访问次数权重
            score += min(memory.metadata.access_count * 0.1, 0.2)

            # 相关度权重
            score += memory.metadata.relevance_score * 0.2

            if score > best_score:
                best_score = score
                best_memory = memory

        return best_memory

    async def _fuse_memory_group(self, group: DuplicateGroup) -> MemoryChunk | None:
        """融合记忆组"""
        if not group.memories:
            return None

        if len(group.memories) == 1:
            return group.memories[0]

        try:
            # 选择基础记忆（通常是代表性记忆）
            base_memory = group.representative_memory or group.memories[0]

            # 融合其他记忆的属性
            fused_memory = await self._merge_memory_attributes(base_memory, group.memories)

            # 更新元数据
            self._update_fused_metadata(fused_memory, group)

            logger.debug(f"成功融合记忆组，包含 {len(group.memories)} 条原始记忆")
            return fused_memory

        except Exception as e:
            logger.error(f"融合记忆组失败: {e}")
            # 返回置信度最高的记忆
            return max(group.memories, key=lambda m: m.metadata.confidence.value)

    async def _merge_memory_attributes(self, base_memory: MemoryChunk, memories: list[MemoryChunk]) -> MemoryChunk:
        """合并记忆属性"""
        # 创建基础记忆的深拷贝
        fused_memory = MemoryChunk.from_dict(base_memory.to_dict())

        # 合并关键词
        all_keywords = set()
        for memory in memories:
            all_keywords.update(memory.keywords)
        fused_memory.keywords = sorted(all_keywords)

        # 合并标签
        all_tags = set()
        for memory in memories:
            all_tags.update(memory.tags)
        fused_memory.tags = sorted(all_tags)

        # 合并分类
        all_categories = set()
        for memory in memories:
            all_categories.update(memory.categories)
        fused_memory.categories = sorted(all_categories)

        # 合并关联记忆
        all_related = set()
        for memory in memories:
            all_related.update(memory.related_memories)
        # 移除对自身和组内记忆的引用
        all_related = {rid for rid in all_related if rid not in [m.memory_id for m in memories]}
        fused_memory.related_memories = sorted(all_related)

        # 合并时间上下文
        if self.fusion_strategies["temporal_proximity"]:
            fused_memory.temporal_context = self._merge_temporal_context(memories)

        return fused_memory

    def _update_fused_metadata(self, fused_memory: MemoryChunk, group: DuplicateGroup):
        """更新融合记忆的元数据"""
        # 更新修改时间
        fused_memory.metadata.last_modified = time.time()

        # 计算平均访问次数
        total_access = sum(m.metadata.access_count for m in group.memories)
        fused_memory.metadata.access_count = total_access

        # 提升置信度（如果有多个来源支持）
        if self.fusion_strategies["confidence_boosting"] and len(group.memories) > 1:
            max_confidence = max(m.metadata.confidence.value for m in group.memories)
            if max_confidence < ConfidenceLevel.VERIFIED.value:
                fused_memory.metadata.confidence = ConfidenceLevel(
                    min(max_confidence + 1, ConfidenceLevel.VERIFIED.value)
                )

        # 保持最高重要性
        if self.fusion_strategies["importance_preservation"]:
            max_importance = max(m.metadata.importance.value for m in group.memories)
            fused_memory.metadata.importance = ImportanceLevel(max_importance)

        # 计算平均相关度
        avg_relevance = sum(m.metadata.relevance_score for m in group.memories) / len(group.memories)
        fused_memory.metadata.relevance_score = min(avg_relevance * 1.1, 1.0)  # 稍微提升相关度

        # 设置来源信息
        source_ids = [m.memory_id[:8] for m in group.memories]
        fused_memory.metadata.source_context = f"Fused from {len(group.memories)} memories: {', '.join(source_ids)}"

    def _merge_temporal_context(self, memories: list[MemoryChunk]) -> dict[str, Any]:
        """合并时间上下文"""
        contexts = [m.temporal_context for m in memories if m.temporal_context]

        if not contexts:
            return {}

        # 计算时间范围
        timestamps = [m.metadata.created_at for m in memories]
        earliest_time = min(timestamps)
        latest_time = max(timestamps)

        merged_context = {
            "earliest_timestamp": earliest_time,
            "latest_timestamp": latest_time,
            "time_span_hours": (latest_time - earliest_time) / 3600,
            "source_memories": len(memories),
        }

        # 合并其他上下文信息
        for context in contexts:
            for key, value in context.items():
                if key not in ["timestamp", "earliest_timestamp", "latest_timestamp"]:
                    if key not in merged_context:
                        merged_context[key] = value
                    elif merged_context[key] != value:
                        merged_context[key] = f"multiple: {value}"

        return merged_context

    async def incremental_fusion(
        self, new_memory: MemoryChunk, existing_memories: list[MemoryChunk]
    ) -> tuple[MemoryChunk, list[MemoryChunk]]:
        """增量融合（单个新记忆与现有记忆融合）"""
        # 寻找相似记忆
        similar_memories = []

        for existing in existing_memories:
            similarity = self._calculate_comprehensive_similarity(new_memory, existing)
            if similarity >= self.similarity_threshold:
                similar_memories.append((existing, similarity))

        if not similar_memories:
            # 没有相似记忆，直接返回
            return new_memory, existing_memories

        # 按相似度排序
        similar_memories.sort(key=lambda x: x[1], reverse=True)

        # 与最相似的记忆融合
        best_match, similarity = similar_memories[0]

        # 创建融合组
        group = DuplicateGroup(
            group_id=f"incremental_{int(time.time())}",
            memories=[new_memory, best_match],
            similarity_matrix=[[1.0, similarity], [similarity, 1.0]],
        )

        # 执行融合
        fused_memory = await self._fuse_memory_group(group)

        # 从现有记忆中移除被融合的记忆
        updated_existing = [m for m in existing_memories if m.memory_id != best_match.memory_id]
        updated_existing.append(fused_memory)

        logger.debug(f"增量融合完成，相似度: {similarity:.3f}")

        return fused_memory, updated_existing

    def _update_fusion_stats(self, original_count: int, removed_count: int, fusion_time: float):
        """更新融合统计"""
        self.fusion_stats["total_fusions"] += 1
        self.fusion_stats["memories_fused"] += original_count
        self.fusion_stats["duplicates_removed"] += removed_count

        # 更新平均相似度（估算）
        if removed_count > 0:
            avg_similarity = 0.9  # 假设平均相似度较高
            total_similarity = self.fusion_stats["average_similarity"] * (self.fusion_stats["total_fusions"] - 1)
            total_similarity += avg_similarity
            self.fusion_stats["average_similarity"] = total_similarity / self.fusion_stats["total_fusions"]

    async def maintenance(self):
        """维护操作"""
        try:
            logger.info("开始记忆融合引擎维护...")

            # 可以在这里添加定期维护任务，如：
            # - 重新评估低置信度记忆
            # - 清理孤立记忆引用
            # - 优化融合策略参数

            logger.info("✅ 记忆融合引擎维护完成")

        except Exception as e:
            logger.error(f"❌ 记忆融合引擎维护失败: {e}", exc_info=True)

    def get_fusion_stats(self) -> dict[str, Any]:
        """获取融合统计信息"""
        return self.fusion_stats.copy()

    def reset_stats(self):
        """重置统计信息"""
        self.fusion_stats = {
            "total_fusions": 0,
            "memories_fused": 0,
            "duplicates_removed": 0,
            "average_similarity": 0.0,
        }
