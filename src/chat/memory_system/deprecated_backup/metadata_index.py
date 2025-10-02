"""
元数据索引系统
为记忆系统提供多维度的精准过滤和查询能力
"""

import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import orjson

from src.chat.memory_system.memory_chunk import ConfidenceLevel, ImportanceLevel, MemoryChunk, MemoryType
from src.common.logger import get_logger

logger = get_logger(__name__)


class IndexType(Enum):
    """索引类型"""

    MEMORY_TYPE = "memory_type"  # 记忆类型索引
    USER_ID = "user_id"  # 用户ID索引
    SUBJECT = "subject"  # 主体索引
    KEYWORD = "keyword"  # 关键词索引
    TAG = "tag"  # 标签索引
    CATEGORY = "category"  # 分类索引
    TIMESTAMP = "timestamp"  # 时间索引
    CONFIDENCE = "confidence"  # 置信度索引
    IMPORTANCE = "importance"  # 重要性索引
    RELATIONSHIP_SCORE = "relationship_score"  # 关系分索引
    ACCESS_FREQUENCY = "access_frequency"  # 访问频率索引
    SEMANTIC_HASH = "semantic_hash"  # 语义哈希索引


@dataclass
class IndexQuery:
    """索引查询条件"""

    user_ids: list[str] | None = None
    memory_types: list[MemoryType] | None = None
    subjects: list[str] | None = None
    keywords: list[str] | None = None
    tags: list[str] | None = None
    categories: list[str] | None = None
    time_range: tuple[float, float] | None = None
    confidence_levels: list[ConfidenceLevel] | None = None
    importance_levels: list[ImportanceLevel] | None = None
    min_relationship_score: float | None = None
    max_relationship_score: float | None = None
    min_access_count: int | None = None
    semantic_hashes: list[str] | None = None
    limit: int | None = None
    sort_by: str | None = None  # "created_at", "access_count", "relevance_score"
    sort_order: str = "desc"  # "asc", "desc"


@dataclass
class IndexResult:
    """索引结果"""

    memory_ids: list[str]
    total_count: int
    query_time: float
    filtered_by: list[str]


class MetadataIndexManager:
    """元数据索引管理器"""

    def __init__(self, index_path: str = "data/memory_metadata"):
        self.index_path = Path(index_path)
        self.index_path.mkdir(parents=True, exist_ok=True)

        # 各类索引
        self.indices = {
            IndexType.MEMORY_TYPE: defaultdict(set),
            IndexType.USER_ID: defaultdict(set),
            IndexType.SUBJECT: defaultdict(set),
            IndexType.KEYWORD: defaultdict(set),
            IndexType.TAG: defaultdict(set),
            IndexType.CATEGORY: defaultdict(set),
            IndexType.CONFIDENCE: defaultdict(set),
            IndexType.IMPORTANCE: defaultdict(set),
            IndexType.SEMANTIC_HASH: defaultdict(set),
        }

        # 时间索引（特殊处理）
        self.time_index = []  # [(timestamp, memory_id), ...]
        self.relationship_index = []  # [(relationship_score, memory_id), ...]
        self.access_frequency_index = []  # [(access_count, memory_id), ...]

        # 内存缓存
        self.memory_metadata_cache: dict[str, dict[str, Any]] = {}

        # 统计信息
        self.index_stats = {
            "total_memories": 0,
            "index_build_time": 0.0,
            "average_query_time": 0.0,
            "total_queries": 0,
            "cache_hit_rate": 0.0,
            "cache_hits": 0,
        }

        # 线程锁
        self._lock = threading.RLock()
        self._dirty = False  # 标记索引是否有未保存的更改

        # 自动保存配置
        self.auto_save_interval = 500  # 每500次操作自动保存
        self._operation_count = 0

    @staticmethod
    def _serialize_index_key(index_type: IndexType, key: Any) -> str:
        """将索引键序列化为字符串以便存储"""
        if isinstance(key, Enum):
            value = key.value
        else:
            value = key
        return str(value)

    @staticmethod
    def _deserialize_index_key(index_type: IndexType, key: str) -> Any:
        """根据索引类型反序列化索引键"""
        try:
            if index_type == IndexType.MEMORY_TYPE:
                return MemoryType(key)
            if index_type == IndexType.CONFIDENCE:
                return ConfidenceLevel(int(key))
            if index_type == IndexType.IMPORTANCE:
                return ImportanceLevel(int(key))
            # 其他索引键默认使用原始字符串（可能已经是lower后的字符串）
            return key
        except Exception:
            logger.warning("无法反序列化索引键 %s 在索引 %s 中，使用原始字符串", key, index_type.value)
            return key

    @staticmethod
    def _serialize_metadata_entry(metadata: dict[str, Any]) -> dict[str, Any]:
        serialized = {}
        for field_name, value in metadata.items():
            if isinstance(value, Enum):
                serialized[field_name] = value.value
            else:
                serialized[field_name] = value
        return serialized

    async def index_memories(self, memories: list[MemoryChunk]):
        """为记忆建立索引"""
        if not memories:
            return

        start_time = time.time()

        try:
            with self._lock:
                for memory in memories:
                    self._index_single_memory(memory)

                # 标记为需要保存
                self._dirty = True
                self._operation_count += len(memories)

                # 自动保存检查
                if self._operation_count >= self.auto_save_interval:
                    await self.save_index()
                    self._operation_count = 0

            index_time = time.time() - start_time
            self.index_stats["index_build_time"] = (
                self.index_stats["index_build_time"] * (len(memories) - 1) + index_time
            ) / len(memories)

            logger.debug(f"元数据索引完成，{len(memories)} 条记忆，耗时 {index_time:.3f}秒")

        except Exception as e:
            logger.error(f"❌ 元数据索引失败: {e}", exc_info=True)

    async def update_memory_entry(self, memory: MemoryChunk):
        """更新已存在记忆的索引信息"""
        if not memory:
            return

        with self._lock:
            entry = self.memory_metadata_cache.get(memory.memory_id)
            if entry is None:
                # 若不存在则作为新记忆索引
                self._index_single_memory(memory)
                return

            old_confidence = entry.get("confidence")
            old_importance = entry.get("importance")
            old_semantic_hash = entry.get("semantic_hash")

            entry.update(
                {
                    "user_id": memory.user_id,
                    "memory_type": memory.memory_type,
                    "created_at": memory.metadata.created_at,
                    "last_accessed": memory.metadata.last_accessed,
                    "access_count": memory.metadata.access_count,
                    "confidence": memory.metadata.confidence,
                    "importance": memory.metadata.importance,
                    "relationship_score": memory.metadata.relationship_score,
                    "relevance_score": memory.metadata.relevance_score,
                    "semantic_hash": memory.semantic_hash,
                    "subjects": memory.subjects,
                }
            )

            # 更新置信度/重要性索引
            if isinstance(old_confidence, ConfidenceLevel):
                self.indices[IndexType.CONFIDENCE][old_confidence].discard(memory.memory_id)
            if isinstance(old_importance, ImportanceLevel):
                self.indices[IndexType.IMPORTANCE][old_importance].discard(memory.memory_id)
            if isinstance(old_semantic_hash, str):
                self.indices[IndexType.SEMANTIC_HASH][old_semantic_hash].discard(memory.memory_id)

            self.indices[IndexType.CONFIDENCE][memory.metadata.confidence].add(memory.memory_id)
            self.indices[IndexType.IMPORTANCE][memory.metadata.importance].add(memory.memory_id)
            if memory.semantic_hash:
                self.indices[IndexType.SEMANTIC_HASH][memory.semantic_hash].add(memory.memory_id)

            # 同步关键词/标签/分类索引
            for keyword in memory.keywords:
                if keyword:
                    self.indices[IndexType.KEYWORD][keyword.lower()].add(memory.memory_id)

            for tag in memory.tags:
                if tag:
                    self.indices[IndexType.TAG][tag.lower()].add(memory.memory_id)

            for category in memory.categories:
                if category:
                    self.indices[IndexType.CATEGORY][category.lower()].add(memory.memory_id)

            for subject in memory.subjects:
                if subject:
                    self.indices[IndexType.SUBJECT][subject.strip().lower()].add(memory.memory_id)

    def _index_single_memory(self, memory: MemoryChunk):
        """为单个记忆建立索引"""
        memory_id = memory.memory_id

        # 更新内存缓存
        self.memory_metadata_cache[memory_id] = {
            "user_id": memory.user_id,
            "memory_type": memory.memory_type,
            "created_at": memory.metadata.created_at,
            "last_accessed": memory.metadata.last_accessed,
            "access_count": memory.metadata.access_count,
            "confidence": memory.metadata.confidence,
            "importance": memory.metadata.importance,
            "relationship_score": memory.metadata.relationship_score,
            "relevance_score": memory.metadata.relevance_score,
            "semantic_hash": memory.semantic_hash,
            "subjects": memory.subjects,
        }

        # 记忆类型索引
        self.indices[IndexType.MEMORY_TYPE][memory.memory_type].add(memory_id)

        # 用户ID索引
        self.indices[IndexType.USER_ID][memory.user_id].add(memory_id)

        # 主体索引
        for subject in memory.subjects:
            normalized = subject.strip().lower()
            if normalized:
                self.indices[IndexType.SUBJECT][normalized].add(memory_id)

        # 关键词索引
        for keyword in memory.keywords:
            self.indices[IndexType.KEYWORD][keyword.lower()].add(memory_id)

        # 标签索引
        for tag in memory.tags:
            self.indices[IndexType.TAG][tag.lower()].add(memory_id)

        # 分类索引
        for category in memory.categories:
            self.indices[IndexType.CATEGORY][category.lower()].add(memory_id)

        # 置信度索引
        self.indices[IndexType.CONFIDENCE][memory.metadata.confidence].add(memory_id)

        # 重要性索引
        self.indices[IndexType.IMPORTANCE][memory.metadata.importance].add(memory_id)

        # 语义哈希索引
        if memory.semantic_hash:
            self.indices[IndexType.SEMANTIC_HASH][memory.semantic_hash].add(memory_id)

        # 时间索引（插入排序保持有序）
        self._insert_into_time_index(memory.metadata.created_at, memory_id)

        # 关系分索引（插入排序保持有序）
        self._insert_into_relationship_index(memory.metadata.relationship_score, memory_id)

        # 访问频率索引（插入排序保持有序）
        self._insert_into_access_frequency_index(memory.metadata.access_count, memory_id)

        # 更新统计
        self.index_stats["total_memories"] += 1

    def _insert_into_time_index(self, timestamp: float, memory_id: str):
        """插入时间索引（保持降序）"""
        insert_pos = len(self.time_index)
        for i, (ts, _) in enumerate(self.time_index):
            if timestamp >= ts:
                insert_pos = i
                break

        self.time_index.insert(insert_pos, (timestamp, memory_id))

    def _insert_into_relationship_index(self, relationship_score: float, memory_id: str):
        """插入关系分索引（保持降序）"""
        insert_pos = len(self.relationship_index)
        for i, (score, _) in enumerate(self.relationship_index):
            if relationship_score >= score:
                insert_pos = i
                break

        self.relationship_index.insert(insert_pos, (relationship_score, memory_id))

    def _insert_into_access_frequency_index(self, access_count: int, memory_id: str):
        """插入访问频率索引（保持降序）"""
        insert_pos = len(self.access_frequency_index)
        for i, (count, _) in enumerate(self.access_frequency_index):
            if access_count >= count:
                insert_pos = i
                break

        self.access_frequency_index.insert(insert_pos, (access_count, memory_id))

    async def query_memories(self, query: IndexQuery) -> IndexResult:
        """查询记忆"""
        start_time = time.time()

        try:
            with self._lock:
                # 获取候选记忆ID集合
                candidate_ids = self._get_candidate_memories(query)

                # 应用过滤条件
                filtered_ids = self._apply_filters(candidate_ids, query)

                # 排序
                if query.sort_by:
                    filtered_ids = self._sort_memories(filtered_ids, query.sort_by, query.sort_order)

                # 限制数量
                if query.limit and len(filtered_ids) > query.limit:
                    filtered_ids = filtered_ids[: query.limit]

                # 记录查询统计
                query_time = time.time() - start_time
                self.index_stats["total_queries"] += 1
                self.index_stats["average_query_time"] = (
                    self.index_stats["average_query_time"] * (self.index_stats["total_queries"] - 1) + query_time
                ) / self.index_stats["total_queries"]

                return IndexResult(
                    memory_ids=filtered_ids,
                    total_count=len(filtered_ids),
                    query_time=query_time,
                    filtered_by=self._get_applied_filters(query),
                )

        except Exception as e:
            logger.error(f"❌ 元数据查询失败: {e}", exc_info=True)
            return IndexResult(memory_ids=[], total_count=0, query_time=0.0, filtered_by=[])

    def _get_candidate_memories(self, query: IndexQuery) -> set[str]:
        """获取候选记忆ID集合"""
        candidate_ids = set()

        # 获取所有记忆ID作为起点
        all_memory_ids = set(self.memory_metadata_cache.keys())

        if not all_memory_ids:
            return candidate_ids

        # 应用最严格的过滤条件
        applied_filters = []

        if query.memory_types:
            memory_types_set = set()
            for memory_type in query.memory_types:
                memory_types_set.update(self.indices[IndexType.MEMORY_TYPE].get(memory_type, set()))
            if applied_filters:
                candidate_ids &= memory_types_set
            else:
                candidate_ids.update(memory_types_set)
            applied_filters.append("memory_types")

        if query.keywords:
            keywords_set = set()
            for keyword in query.keywords:
                keywords_set.update(self._collect_index_matches(IndexType.KEYWORD, keyword))
            if applied_filters:
                candidate_ids &= keywords_set
            else:
                candidate_ids.update(keywords_set)
            applied_filters.append("keywords")

        if query.tags:
            tags_set = set()
            for tag in query.tags:
                tags_set.update(self.indices[IndexType.TAG].get(tag.lower(), set()))
            if applied_filters:
                candidate_ids &= tags_set
            else:
                candidate_ids.update(tags_set)
            applied_filters.append("tags")

        if query.categories:
            categories_set = set()
            for category in query.categories:
                categories_set.update(self.indices[IndexType.CATEGORY].get(category.lower(), set()))
            if applied_filters:
                candidate_ids &= categories_set
            else:
                candidate_ids.update(categories_set)
            applied_filters.append("categories")

        if query.subjects:
            subjects_set = set()
            for subject in query.subjects:
                subjects_set.update(self._collect_index_matches(IndexType.SUBJECT, subject))
            if applied_filters:
                candidate_ids &= subjects_set
            else:
                candidate_ids.update(subjects_set)
            applied_filters.append("subjects")

        # 如果没有应用任何过滤条件，返回所有记忆
        if not applied_filters:
            return all_memory_ids

        return candidate_ids

    def _collect_index_matches(self, index_type: IndexType, token: str | Enum | None) -> set[str]:
        """根据给定token收集索引匹配，支持部分匹配"""
        mapping = self.indices.get(index_type)
        if mapping is None:
            return set()

        key = ""
        if isinstance(token, Enum):
            key = str(token.value).strip().lower()
        elif isinstance(token, str):
            key = token.strip().lower()
        elif token is not None:
            key = str(token).strip().lower()

        if not key:
            return set()

        matches: set[str] = set(mapping.get(key, set()))

        if matches:
            return set(matches)

        for existing_key, ids in mapping.items():
            if not existing_key or not isinstance(existing_key, str):
                continue
            normalized = existing_key.strip().lower()
            if not normalized:
                continue
            if key in normalized or normalized in key:
                matches.update(ids)

        return matches

    def _apply_filters(self, candidate_ids: set[str], query: IndexQuery) -> list[str]:
        """应用过滤条件"""
        filtered_ids = list(candidate_ids)

        # 时间范围过滤
        if query.time_range:
            start_time, end_time = query.time_range
            filtered_ids = [
                memory_id for memory_id in filtered_ids if self._is_in_time_range(memory_id, start_time, end_time)
            ]

        # 置信度过滤
        if query.confidence_levels:
            confidence_set = set(query.confidence_levels)
            filtered_ids = [
                memory_id
                for memory_id in filtered_ids
                if self.memory_metadata_cache[memory_id]["confidence"] in confidence_set
            ]

        # 重要性过滤
        if query.importance_levels:
            importance_set = set(query.importance_levels)
            filtered_ids = [
                memory_id
                for memory_id in filtered_ids
                if self.memory_metadata_cache[memory_id]["importance"] in importance_set
            ]

        # 关系分范围过滤
        if query.min_relationship_score is not None:
            filtered_ids = [
                memory_id
                for memory_id in filtered_ids
                if self.memory_metadata_cache[memory_id]["relationship_score"] >= query.min_relationship_score
            ]

        if query.max_relationship_score is not None:
            filtered_ids = [
                memory_id
                for memory_id in filtered_ids
                if self.memory_metadata_cache[memory_id]["relationship_score"] <= query.max_relationship_score
            ]

        # 最小访问次数过滤
        if query.min_access_count is not None:
            filtered_ids = [
                memory_id
                for memory_id in filtered_ids
                if self.memory_metadata_cache[memory_id]["access_count"] >= query.min_access_count
            ]

        # 语义哈希过滤
        if query.semantic_hashes:
            hash_set = set(query.semantic_hashes)
            filtered_ids = [
                memory_id
                for memory_id in filtered_ids
                if self.memory_metadata_cache[memory_id]["semantic_hash"] in hash_set
            ]

        return filtered_ids

    def _is_in_time_range(self, memory_id: str, start_time: float, end_time: float) -> bool:
        """检查记忆是否在时间范围内"""
        created_at = self.memory_metadata_cache[memory_id]["created_at"]
        return start_time <= created_at <= end_time

    def _sort_memories(self, memory_ids: list[str], sort_by: str, sort_order: str) -> list[str]:
        """对记忆进行排序"""
        if sort_by == "created_at":
            # 使用时间索引（已经有序）
            if sort_order == "desc":
                return memory_ids  # 时间索引已经是降序
            else:
                return memory_ids[::-1]  # 反转为升序

        elif sort_by == "access_count":
            # 使用访问频率索引（已经有序）
            if sort_order == "desc":
                return memory_ids  # 访问频率索引已经是降序
            else:
                return memory_ids[::-1]  # 反转为升序

        elif sort_by == "relevance_score":
            # 按相关度排序
            memory_ids.sort(
                key=lambda mid: self.memory_metadata_cache[mid]["relevance_score"], reverse=(sort_order == "desc")
            )

        elif sort_by == "relationship_score":
            # 使用关系分索引（已经有序）
            if sort_order == "desc":
                return memory_ids  # 关系分索引已经是降序
            else:
                return memory_ids[::-1]  # 反转为升序

        elif sort_by == "last_accessed":
            # 按最后访问时间排序
            memory_ids.sort(
                key=lambda mid: self.memory_metadata_cache[mid]["last_accessed"], reverse=(sort_order == "desc")
            )

        return memory_ids

    def _get_applied_filters(self, query: IndexQuery) -> list[str]:
        """获取应用的过滤器列表"""
        filters = []
        if query.memory_types:
            filters.append("memory_types")
        if query.subjects:
            filters.append("subjects")
        if query.keywords:
            filters.append("keywords")
        if query.tags:
            filters.append("tags")
        if query.categories:
            filters.append("categories")
        if query.time_range:
            filters.append("time_range")
        if query.confidence_levels:
            filters.append("confidence_levels")
        if query.importance_levels:
            filters.append("importance_levels")
        if query.min_relationship_score is not None or query.max_relationship_score is not None:
            filters.append("relationship_score_range")
        if query.min_access_count is not None:
            filters.append("min_access_count")
        if query.semantic_hashes:
            filters.append("semantic_hashes")
        return filters

    async def update_memory_index(self, memory: MemoryChunk):
        """更新记忆索引"""
        with self._lock:
            try:
                memory_id = memory.memory_id

                # 如果记忆已存在，先删除旧索引
                if memory_id in self.memory_metadata_cache:
                    await self.remove_memory_index(memory_id)

                # 重新建立索引
                self._index_single_memory(memory)
                self._dirty = True
                self._operation_count += 1

                # 自动保存检查
                if self._operation_count >= self.auto_save_interval:
                    await self.save_index()
                    self._operation_count = 0

                logger.debug(f"更新记忆索引完成: {memory_id}")

            except Exception as e:
                logger.error(f"❌ 更新记忆索引失败: {e}")

    async def remove_memory_index(self, memory_id: str):
        """移除记忆索引"""
        with self._lock:
            try:
                if memory_id not in self.memory_metadata_cache:
                    return

                # 获取记忆元数据
                metadata = self.memory_metadata_cache[memory_id]

                # 从各类索引中移除
                self.indices[IndexType.MEMORY_TYPE][metadata["memory_type"]].discard(memory_id)
                self.indices[IndexType.USER_ID][metadata["user_id"]].discard(memory_id)
                subjects = metadata.get("subjects") or []
                for subject in subjects:
                    if not isinstance(subject, str):
                        continue
                    normalized = subject.strip().lower()
                    if not normalized:
                        continue
                    subject_bucket = self.indices[IndexType.SUBJECT].get(normalized)
                    if subject_bucket is not None:
                        subject_bucket.discard(memory_id)
                        if not subject_bucket:
                            self.indices[IndexType.SUBJECT].pop(normalized, None)

                # 从时间索引中移除
                self.time_index = [(ts, mid) for ts, mid in self.time_index if mid != memory_id]

                # 从关系分索引中移除
                self.relationship_index = [(score, mid) for score, mid in self.relationship_index if mid != memory_id]

                # 从访问频率索引中移除
                self.access_frequency_index = [
                    (count, mid) for count, mid in self.access_frequency_index if mid != memory_id
                ]

                # 注意：关键词、标签、分类索引需要从原始记忆中获取，这里简化处理
                # 实际实现中可能需要重新加载记忆或维护反向索引

                # 从缓存中移除
                del self.memory_metadata_cache[memory_id]

                # 更新统计
                self.index_stats["total_memories"] = max(0, self.index_stats["total_memories"] - 1)
                self._dirty = True

                logger.debug(f"移除记忆索引完成: {memory_id}")

            except Exception as e:
                logger.error(f"❌ 移除记忆索引失败: {e}")

    async def get_memory_metadata(self, memory_id: str) -> dict[str, Any] | None:
        """获取记忆元数据"""
        return self.memory_metadata_cache.get(memory_id)

    async def get_user_memory_ids(self, user_id: str, limit: int | None = None) -> list[str]:
        """获取用户的所有记忆ID"""
        user_memory_ids = list(self.indices[IndexType.USER_ID].get(user_id, set()))

        if limit and len(user_memory_ids) > limit:
            user_memory_ids = user_memory_ids[:limit]

        return user_memory_ids

    async def get_memory_statistics(self, user_id: str | None = None) -> dict[str, Any]:
        """获取记忆统计信息"""
        stats = {
            "total_memories": self.index_stats["total_memories"],
            "memory_types": {},
            "average_confidence": 0.0,
            "average_importance": 0.0,
            "average_relationship_score": 0.0,
            "top_keywords": [],
            "top_tags": [],
        }

        if user_id:
            # 限定用户统计
            user_memory_ids = self.indices[IndexType.USER_ID].get(user_id, set())
            stats["user_total_memories"] = len(user_memory_ids)

            if not user_memory_ids:
                return stats

            # 用户记忆类型分布
            user_types = {}
            for memory_type, memory_ids in self.indices[IndexType.MEMORY_TYPE].items():
                user_count = len(user_memory_ids & memory_ids)
                if user_count > 0:
                    user_types[memory_type.value] = user_count
            stats["memory_types"] = user_types

            # 计算用户平均值
            user_confidences = []
            user_importances = []
            user_relationship_scores = []

            for memory_id in user_memory_ids:
                metadata = self.memory_metadata_cache.get(memory_id, {})
                if metadata:
                    user_confidences.append(metadata["confidence"].value)
                    user_importances.append(metadata["importance"].value)
                    user_relationship_scores.append(metadata["relationship_score"])

            if user_confidences:
                stats["average_confidence"] = sum(user_confidences) / len(user_confidences)
            if user_importances:
                stats["average_importance"] = sum(user_importances) / len(user_importances)
            if user_relationship_scores:
                stats["average_relationship_score"] = sum(user_relationship_scores) / len(user_relationship_scores)

        else:
            # 全局统计
            for memory_type, memory_ids in self.indices[IndexType.MEMORY_TYPE].items():
                stats["memory_types"][memory_type.value] = len(memory_ids)

            # 计算全局平均值
            if self.memory_metadata_cache:
                all_confidences = [m["confidence"].value for m in self.memory_metadata_cache.values()]
                all_importances = [m["importance"].value for m in self.memory_metadata_cache.values()]
                all_relationship_scores = [m["relationship_score"] for m in self.memory_metadata_cache.values()]

                if all_confidences:
                    stats["average_confidence"] = sum(all_confidences) / len(all_confidences)
                if all_importances:
                    stats["average_importance"] = sum(all_importances) / len(all_importances)
                if all_relationship_scores:
                    stats["average_relationship_score"] = sum(all_relationship_scores) / len(all_relationship_scores)

        # 统计热门关键词和标签
        keyword_counts = [(keyword, len(memory_ids)) for keyword, memory_ids in self.indices[IndexType.KEYWORD].items()]
        keyword_counts.sort(key=lambda x: x[1], reverse=True)
        stats["top_keywords"] = keyword_counts[:10]

        tag_counts = [(tag, len(memory_ids)) for tag, memory_ids in self.indices[IndexType.TAG].items()]
        tag_counts.sort(key=lambda x: x[1], reverse=True)
        stats["top_tags"] = tag_counts[:10]

        return stats

    async def save_index(self):
        """保存索引到文件"""
        if not self._dirty:
            return

        try:
            logger.info("正在保存元数据索引...")

            # 保存各类索引
            indices_data: dict[str, dict[str, list[str]]] = {}
            for index_type, index_data in self.indices.items():
                serialized_index = {}
                for key, values in index_data.items():
                    serialized_key = self._serialize_index_key(index_type, key)
                    serialized_index[serialized_key] = list(values)
                indices_data[index_type.value] = serialized_index

            indices_file = self.index_path / "indices.json"
            with open(indices_file, "w", encoding="utf-8") as f:
                f.write(orjson.dumps(indices_data, option=orjson.OPT_INDENT_2).decode("utf-8"))

            # 保存时间索引
            time_index_file = self.index_path / "time_index.json"
            with open(time_index_file, "w", encoding="utf-8") as f:
                f.write(orjson.dumps(self.time_index, option=orjson.OPT_INDENT_2).decode("utf-8"))

            # 保存关系分索引
            relationship_index_file = self.index_path / "relationship_index.json"
            with open(relationship_index_file, "w", encoding="utf-8") as f:
                f.write(orjson.dumps(self.relationship_index, option=orjson.OPT_INDENT_2).decode("utf-8"))

            # 保存访问频率索引
            access_frequency_index_file = self.index_path / "access_frequency_index.json"
            with open(access_frequency_index_file, "w", encoding="utf-8") as f:
                f.write(orjson.dumps(self.access_frequency_index, option=orjson.OPT_INDENT_2).decode("utf-8"))

            # 保存元数据缓存
            metadata_cache_file = self.index_path / "metadata_cache.json"
            metadata_serialized = {
                memory_id: self._serialize_metadata_entry(metadata)
                for memory_id, metadata in self.memory_metadata_cache.items()
            }
            with open(metadata_cache_file, "w", encoding="utf-8") as f:
                f.write(orjson.dumps(metadata_serialized, option=orjson.OPT_INDENT_2).decode("utf-8"))

            # 保存统计信息
            stats_file = self.index_path / "index_stats.json"
            with open(stats_file, "w", encoding="utf-8") as f:
                f.write(orjson.dumps(self.index_stats, option=orjson.OPT_INDENT_2).decode("utf-8"))

            self._dirty = False
            logger.info("✅ 元数据索引保存完成")

        except Exception as e:
            logger.error(f"❌ 保存元数据索引失败: {e}")

    async def load_index(self):
        """从文件加载索引"""
        try:
            logger.info("正在加载元数据索引...")

            # 加载各类索引
            indices_file = self.index_path / "indices.json"
            if indices_file.exists():
                with open(indices_file, encoding="utf-8") as f:
                    indices_data = orjson.loads(f.read())

                for index_type_value, index_data in indices_data.items():
                    index_type = IndexType(index_type_value)
                    restored_index = defaultdict(set)
                    for key_str, values in index_data.items():
                        restored_key = self._deserialize_index_key(index_type, key_str)
                        restored_index[restored_key] = set(values)
                    self.indices[index_type] = restored_index

            # 加载时间索引
            time_index_file = self.index_path / "time_index.json"
            if time_index_file.exists():
                with open(time_index_file, encoding="utf-8") as f:
                    self.time_index = orjson.loads(f.read())

            # 加载关系分索引
            relationship_index_file = self.index_path / "relationship_index.json"
            if relationship_index_file.exists():
                with open(relationship_index_file, encoding="utf-8") as f:
                    self.relationship_index = orjson.loads(f.read())

            # 加载访问频率索引
            access_frequency_index_file = self.index_path / "access_frequency_index.json"
            if access_frequency_index_file.exists():
                with open(access_frequency_index_file, encoding="utf-8") as f:
                    self.access_frequency_index = orjson.loads(f.read())

            # 加载元数据缓存
            metadata_cache_file = self.index_path / "metadata_cache.json"
            if metadata_cache_file.exists():
                with open(metadata_cache_file, encoding="utf-8") as f:
                    cache_data = orjson.loads(f.read())

                # 转换置信度和重要性为枚举类型
                for memory_id, metadata in cache_data.items():
                    memory_type_value = metadata.get("memory_type")
                    if isinstance(memory_type_value, str):
                        try:
                            metadata["memory_type"] = MemoryType(memory_type_value)
                        except ValueError:
                            logger.warning("无法解析memory_type %s", memory_type_value)

                    confidence_value = metadata.get("confidence")
                    if isinstance(confidence_value, (str, int)):
                        try:
                            metadata["confidence"] = ConfidenceLevel(int(confidence_value))
                        except ValueError:
                            logger.warning("无法解析confidence %s", confidence_value)

                    importance_value = metadata.get("importance")
                    if isinstance(importance_value, (str, int)):
                        try:
                            metadata["importance"] = ImportanceLevel(int(importance_value))
                        except ValueError:
                            logger.warning("无法解析importance %s", importance_value)

                    subjects_value = metadata.get("subjects")
                    if isinstance(subjects_value, str):
                        metadata["subjects"] = [subjects_value]
                    elif isinstance(subjects_value, list):
                        cleaned_subjects = []
                        for item in subjects_value:
                            if isinstance(item, str) and item.strip():
                                cleaned_subjects.append(item.strip())
                        metadata["subjects"] = cleaned_subjects
                    else:
                        metadata["subjects"] = []

                self.memory_metadata_cache = cache_data

            # 加载统计信息
            stats_file = self.index_path / "index_stats.json"
            if stats_file.exists():
                with open(stats_file, encoding="utf-8") as f:
                    self.index_stats = orjson.loads(f.read())

            # 更新记忆计数
            self.index_stats["total_memories"] = len(self.memory_metadata_cache)

            logger.info(f"✅ 元数据索引加载完成，{self.index_stats['total_memories']} 个记忆")

        except Exception as e:
            logger.error(f"❌ 加载元数据索引失败: {e}")

    async def optimize_index(self):
        """优化索引"""
        try:
            logger.info("开始元数据索引优化...")

            # 清理无效引用
            self._cleanup_invalid_references()

            # 重建有序索引
            self._rebuild_ordered_indices()

            # 清理低频关键词和标签
            self._cleanup_low_frequency_terms()

            # 更新统计信息
            if self.index_stats["total_queries"] > 0:
                self.index_stats["cache_hit_rate"] = self.index_stats["cache_hits"] / self.index_stats["total_queries"]

            logger.info("✅ 元数据索引优化完成")

        except Exception as e:
            logger.error(f"❌ 元数据索引优化失败: {e}")

    def _cleanup_invalid_references(self):
        """清理无效引用"""
        valid_memory_ids = set(self.memory_metadata_cache.keys())

        # 清理各类索引中的无效引用
        for index_type in self.indices:
            for key in list(self.indices[index_type].keys()):
                valid_ids = self.indices[index_type][key] & valid_memory_ids
                self.indices[index_type][key] = valid_ids

                # 如果某类别下没有记忆了，删除该类别
                if not valid_ids:
                    del self.indices[index_type][key]

        # 清理时间索引中的无效引用
        self.time_index = [(ts, mid) for ts, mid in self.time_index if mid in valid_memory_ids]

        # 清理关系分索引中的无效引用
        self.relationship_index = [(score, mid) for score, mid in self.relationship_index if mid in valid_memory_ids]

        # 清理访问频率索引中的无效引用
        self.access_frequency_index = [
            (count, mid) for count, mid in self.access_frequency_index if mid in valid_memory_ids
        ]

        # 更新总记忆数
        self.index_stats["total_memories"] = len(valid_memory_ids)

    def _rebuild_ordered_indices(self):
        """重建有序索引"""
        # 重建时间索引
        self.time_index.sort(key=lambda x: x[0], reverse=True)

        # 重建关系分索引
        self.relationship_index.sort(key=lambda x: x[0], reverse=True)

        # 重建访问频率索引
        self.access_frequency_index.sort(key=lambda x: x[0], reverse=True)

    def _cleanup_low_frequency_terms(self, min_frequency: int = 2):
        """清理低频术语"""
        # 清理低频关键词
        for keyword in list(self.indices[IndexType.KEYWORD].keys()):
            if len(self.indices[IndexType.KEYWORD][keyword]) < min_frequency:
                del self.indices[IndexType.KEYWORD][keyword]

        # 清理低频标签
        for tag in list(self.indices[IndexType.TAG].keys()):
            if len(self.indices[IndexType.TAG][tag]) < min_frequency:
                del self.indices[IndexType.TAG][tag]

        # 清理低频分类
        for category in list(self.indices[IndexType.CATEGORY].keys()):
            if len(self.indices[IndexType.CATEGORY][category]) < min_frequency:
                del self.indices[IndexType.CATEGORY][category]

    def get_index_stats(self) -> dict[str, Any]:
        """获取索引统计信息"""
        stats = self.index_stats.copy()
        if stats["total_queries"] > 0:
            stats["cache_hit_rate"] = stats["cache_hits"] / stats["total_queries"]
        else:
            stats["cache_hit_rate"] = 0.0

        # 添加索引详细信息
        stats["index_details"] = {
            "memory_types": len(self.indices[IndexType.MEMORY_TYPE]),
            "user_ids": len(self.indices[IndexType.USER_ID]),
            "keywords": len(self.indices[IndexType.KEYWORD]),
            "tags": len(self.indices[IndexType.TAG]),
            "categories": len(self.indices[IndexType.CATEGORY]),
            "confidence_levels": len(self.indices[IndexType.CONFIDENCE]),
            "importance_levels": len(self.indices[IndexType.IMPORTANCE]),
            "semantic_hashes": len(self.indices[IndexType.SEMANTIC_HASH]),
        }

        return stats
