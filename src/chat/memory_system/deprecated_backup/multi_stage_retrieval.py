"""
多阶段召回机制
实现粗粒度到细粒度的记忆检索优化
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import orjson

from src.chat.memory_system.enhanced_reranker import EnhancedReRanker, ReRankingConfig
from src.chat.memory_system.memory_chunk import MemoryChunk, MemoryType
from src.common.logger import get_logger

logger = get_logger(__name__)


class RetrievalStage(Enum):
    """检索阶段"""

    METADATA_FILTERING = "metadata_filtering"  # 元数据过滤阶段
    VECTOR_SEARCH = "vector_search"  # 向量搜索阶段
    SEMANTIC_RERANKING = "semantic_reranking"  # 语义重排序阶段
    CONTEXTUAL_FILTERING = "contextual_filtering"  # 上下文过滤阶段


@dataclass
class RetrievalConfig:
    """检索配置"""

    # 各阶段配置 - 优化召回率
    metadata_filter_limit: int = 150  # 元数据过滤阶段返回数量（增加）
    vector_search_limit: int = 80  # 向量搜索阶段返回数量（增加）
    semantic_rerank_limit: int = 30  # 语义重排序阶段返回数量（增加）
    final_result_limit: int = 10  # 最终结果数量

    # 相似度阈值 - 优化召回率
    vector_similarity_threshold: float = 0.5  # 向量相似度阈值（降低以提升召回率）
    semantic_similarity_threshold: float = 0.05  # 语义相似度阈值（保持较低以获得更多相关记忆）

    # 权重配置
    vector_weight: float = 0.4  # 向量相似度权重
    semantic_weight: float = 0.3  # 语义相似度权重
    context_weight: float = 0.2  # 上下文权重
    recency_weight: float = 0.1  # 时效性权重

    @classmethod
    def from_global_config(cls):
        """从全局配置创建配置实例"""
        from src.config.config import global_config

        return cls(
            # 各阶段配置 - 优化召回率
            metadata_filter_limit=max(150, global_config.memory.metadata_filter_limit),  # 增加候选池
            vector_search_limit=max(80, global_config.memory.vector_search_limit),  # 增加向量搜索结果
            semantic_rerank_limit=max(30, global_config.memory.semantic_rerank_limit),  # 增加重排序候选
            final_result_limit=global_config.memory.final_result_limit,
            # 相似度阈值 - 优化召回率
            vector_similarity_threshold=max(0.5, global_config.memory.vector_similarity_threshold),  # 确保不低于0.5
            semantic_similarity_threshold=0.05,  # 进一步降低以提升召回率
            # 权重配置
            vector_weight=global_config.memory.vector_weight,
            semantic_weight=global_config.memory.semantic_weight,
            context_weight=global_config.memory.context_weight,
            recency_weight=global_config.memory.recency_weight,
        )


@dataclass
class StageResult:
    """阶段结果"""

    stage: RetrievalStage
    memory_ids: list[str]
    processing_time: float
    filtered_count: int
    score_threshold: float
    details: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RetrievalResult:
    """检索结果"""

    query: str
    user_id: str
    final_memories: list[MemoryChunk]
    stage_results: list[StageResult]
    total_processing_time: float
    total_filtered: int
    retrieval_stats: dict[str, Any]


class MultiStageRetrieval:
    """多阶段召回系统"""

    def __init__(self, config: RetrievalConfig | None = None):
        self.config = config or RetrievalConfig.from_global_config()

        # 初始化增强重排序器
        reranker_config = ReRankingConfig(
            semantic_weight=self.config.vector_weight,
            recency_weight=self.config.recency_weight,
            usage_freq_weight=0.2,  # 新增的使用频率权重
            type_match_weight=0.1,  # 新增的类型匹配权重
        )
        self.reranker = EnhancedReRanker(reranker_config)

        self.retrieval_stats = {
            "total_queries": 0,
            "average_retrieval_time": 0.0,
            "stage_stats": {
                "metadata_filtering": {"calls": 0, "avg_time": 0.0},
                "vector_search": {"calls": 0, "avg_time": 0.0},
                "semantic_reranking": {"calls": 0, "avg_time": 0.0},
                "contextual_filtering": {"calls": 0, "avg_time": 0.0},
                "enhanced_reranking": {"calls": 0, "avg_time": 0.0},  # 新增统计
            },
        }

    async def retrieve_memories(
        self,
        query: str,
        user_id: str,
        context: dict[str, Any],
        metadata_index,
        vector_storage,
        all_memories_cache: dict[str, MemoryChunk],
        limit: int | None = None,
    ) -> RetrievalResult:
        """多阶段记忆检索"""
        start_time = time.time()
        limit = limit or self.config.final_result_limit

        stage_results = []
        current_memory_ids = set()
        memory_debug_info: dict[str, dict[str, Any]] = {}

        try:
            logger.debug(f"开始多阶段检索：query='{query}', user_id='{user_id}'")

            # 阶段1：元数据过滤
            stage1_result = await self._metadata_filtering_stage(
                query, user_id, context, metadata_index, all_memories_cache, debug_log=memory_debug_info
            )
            stage_results.append(stage1_result)
            current_memory_ids.update(stage1_result.memory_ids)

            # 阶段2：向量搜索
            stage2_result = await self._vector_search_stage(
                query,
                user_id,
                context,
                vector_storage,
                current_memory_ids,
                all_memories_cache,
                debug_log=memory_debug_info,
            )
            stage_results.append(stage2_result)
            current_memory_ids.update(stage2_result.memory_ids)

            # 阶段3：语义重排序
            stage3_result = await self._semantic_reranking_stage(
                query, user_id, context, current_memory_ids, all_memories_cache, debug_log=memory_debug_info
            )
            stage_results.append(stage3_result)

            # 阶段4：上下文过滤
            stage4_result = await self._contextual_filtering_stage(
                query,
                user_id,
                context,
                stage3_result.memory_ids,
                all_memories_cache,
                limit,
                debug_log=memory_debug_info,
            )
            stage_results.append(stage4_result)

            # 检查是否需要回退机制
            if len(stage4_result.memory_ids) < min(3, limit):
                logger.debug(f"上下文过滤结果过少({len(stage4_result.memory_ids)})，启用回退机制")
                # 回退到更宽松的检索策略
                fallback_result = await self._fallback_retrieval_stage(
                    query,
                    user_id,
                    context,
                    all_memories_cache,
                    limit,
                    excluded_ids=set(stage4_result.memory_ids),
                    debug_log=memory_debug_info,
                )
                if fallback_result.memory_ids:
                    stage4_result.memory_ids.extend(fallback_result.memory_ids[: limit - len(stage4_result.memory_ids)])
                    logger.debug(f"回退机制补充了 {len(fallback_result.memory_ids)} 条记忆")

            # 阶段5：增强重排序 (新增)
            stage5_result = await self._enhanced_reranking_stage(
                query,
                user_id,
                context,
                stage4_result.memory_ids,
                all_memories_cache,
                limit,
                debug_log=memory_debug_info,
            )
            stage_results.append(stage5_result)

            # 获取最终记忆对象
            final_memories = []
            for memory_id in stage5_result.memory_ids:  # 使用重排序后的结果
                if memory_id in all_memories_cache:
                    memory = all_memories_cache[memory_id]
                    memory.update_access()  # 更新访问统计
                    final_memories.append(memory)

            # 更新统计
            total_time = time.time() - start_time
            self._update_retrieval_stats(total_time, stage_results)

            total_filtered = sum(result.filtered_count for result in stage_results)

            logger.debug(f"多阶段检索完成：返回 {len(final_memories)} 条记忆，耗时 {total_time:.3f}s")

            if memory_debug_info:
                final_ids_set = set(stage5_result.memory_ids)  # 使用重排序后的结果
                debug_entries = []
                for memory_id, trace in memory_debug_info.items():
                    memory_obj = all_memories_cache.get(memory_id)
                    display_text = ""
                    if memory_obj:
                        display_text = (memory_obj.display or memory_obj.text_content or "").strip()
                        if len(display_text) > 80:
                            display_text = display_text[:77] + "..."

                    entry = {
                        "memory_id": memory_id,
                        "display": display_text,
                        "memory_type": memory_obj.memory_type.value if memory_obj else None,
                        "vector_similarity": trace.get("vector_stage", {}).get("similarity"),
                        "semantic_score": trace.get("semantic_stage", {}).get("score"),
                        "context_score": trace.get("context_stage", {}).get("context_score"),
                        "final_score": trace.get("context_stage", {}).get("final_score"),
                        "status": trace.get("context_stage", {}).get("status")
                        or trace.get("vector_stage", {}).get("status")
                        or trace.get("semantic_stage", {}).get("status"),
                        "is_final": memory_id in final_ids_set,
                    }
                    debug_entries.append(entry)

                # 限制日志输出数量
                debug_entries.sort(
                    key=lambda item: (
                        item.get("is_final", False),
                        item.get("final_score") or item.get("vector_similarity") or 0.0,
                    ),
                    reverse=True,
                )
                debug_payload = {
                    "query": query,
                    "semantic_query": context.get("resolved_query_text", query),
                    "user_id": user_id,
                    "stage_summaries": [
                        {
                            "stage": result.stage.value,
                            "returned": len(result.memory_ids),
                            "filtered": result.filtered_count,
                            "duration": round(result.processing_time, 4),
                            "details": result.details,
                        }
                        for result in stage_results
                    ],
                    "candidates": debug_entries[:20],
                }
                try:
                    logger.info(
                        f"🧭 记忆检索调试 | query='{query}' | final={len(stage5_result.memory_ids)}",
                        extra={"memory_debug": debug_payload},
                    )
                except Exception:
                    logger.info(
                        f"🧭 记忆检索调试详情: {orjson.dumps(debug_payload, ensure_ascii=False).decode('utf-8')}",
                    )

            return RetrievalResult(
                query=query,
                user_id=user_id,
                final_memories=final_memories,
                stage_results=stage_results,
                total_processing_time=total_time,
                total_filtered=total_filtered,
                retrieval_stats=self.retrieval_stats.copy(),
            )

        except Exception as e:
            logger.error(f"多阶段检索失败: {e}", exc_info=True)
            # 返回空结果
            return RetrievalResult(
                query=query,
                user_id=user_id,
                final_memories=[],
                stage_results=stage_results,
                total_processing_time=time.time() - start_time,
                total_filtered=0,
                retrieval_stats=self.retrieval_stats.copy(),
            )

    async def _metadata_filtering_stage(
        self,
        query: str,
        user_id: str,
        context: dict[str, Any],
        metadata_index,
        all_memories_cache: dict[str, MemoryChunk],
        *,
        debug_log: dict[str, dict[str, Any]] | None = None,
    ) -> StageResult:
        """阶段1：元数据过滤"""
        start_time = time.time()

        try:
            from .metadata_index import IndexQuery

            query_plan = context.get("query_plan")

            memory_types = self._extract_memory_types_from_context(context)
            keywords = self._extract_keywords_from_query(query, query_plan)
            subjects = (
                query_plan.subject_includes if query_plan and getattr(query_plan, "subject_includes", None) else None
            )

            index_query = IndexQuery(
                user_ids=None,
                memory_types=memory_types,
                subjects=subjects,
                keywords=keywords,
                limit=self.config.metadata_filter_limit,
                sort_by="last_accessed",
                sort_order="desc",
            )

            # 执行查询
            result = await metadata_index.query_memories(index_query)
            result_ids = list(result.memory_ids)
            filtered_count = max(0, len(all_memories_cache) - len(result_ids))
            details: list[dict[str, Any]] = []

            # 如果未命中任何索引且未指定所有者过滤，则回退到最近访问的记忆
            if not result_ids:
                sorted_ids = sorted(
                    (memory.memory_id for memory in all_memories_cache.values()),
                    key=lambda mid: all_memories_cache[mid].metadata.last_accessed if mid in all_memories_cache else 0,
                    reverse=True,
                )
                if memory_types:
                    type_filtered = [mid for mid in sorted_ids if all_memories_cache[mid].memory_type in memory_types]
                    sorted_ids = type_filtered or sorted_ids
                if subjects:
                    subject_candidates = [s.lower() for s in subjects if isinstance(s, str) and s.strip()]
                    if subject_candidates:
                        subject_filtered = [
                            mid
                            for mid in sorted_ids
                            if any(
                                subj.strip().lower() in subject_candidates for subj in all_memories_cache[mid].subjects
                            )
                        ]
                        sorted_ids = subject_filtered or sorted_ids

                if keywords:
                    keyword_pool = {kw.lower() for kw in keywords if isinstance(kw, str) and kw.strip()}
                    if keyword_pool:
                        keyword_filtered = []
                        for mid in sorted_ids:
                            memory_text = (
                                (all_memories_cache[mid].display or "")
                                + "\n"
                                + (all_memories_cache[mid].text_content or "")
                            ).lower()
                            if any(kw in memory_text for kw in keyword_pool):
                                keyword_filtered.append(mid)
                        sorted_ids = keyword_filtered or sorted_ids

                result_ids = sorted_ids[: self.config.metadata_filter_limit]
                filtered_count = max(0, len(all_memories_cache) - len(result_ids))
                logger.debug(
                    "元数据过滤未命中索引，使用近似回退: types=%s, subjects=%s, keywords=%s",
                    bool(memory_types),
                    bool(subjects),
                    bool(keywords),
                )
                details.append(
                    {
                        "note": "fallback_recent",
                        "requested_types": [mt.value for mt in memory_types] if memory_types else [],
                        "subjects": subjects or [],
                        "keywords": keywords or [],
                    }
                )

            logger.debug(
                "元数据过滤：候选=%d, 返回=%d",
                len(all_memories_cache),
                len(result_ids),
            )

            for memory_id in result_ids[:20]:
                detail_entry = {
                    "memory_id": memory_id,
                    "status": "candidate",
                }
                details.append(detail_entry)
                if debug_log is not None:
                    stage_entry = debug_log.setdefault(memory_id, {}).setdefault("metadata_stage", {})
                    stage_entry["status"] = "candidate"

            return StageResult(
                stage=RetrievalStage.METADATA_FILTERING,
                memory_ids=result_ids,
                processing_time=time.time() - start_time,
                filtered_count=filtered_count,
                score_threshold=0.0,
                details=details,
            )

        except Exception as e:
            logger.error(f"元数据过滤阶段失败: {e}")
            return StageResult(
                stage=RetrievalStage.METADATA_FILTERING,
                memory_ids=[],
                processing_time=time.time() - start_time,
                filtered_count=0,
                score_threshold=0.0,
                details=[{"error": str(e)}],
            )

    async def _vector_search_stage(
        self,
        query: str,
        user_id: str,
        context: dict[str, Any],
        vector_storage,
        candidate_ids: set[str],
        all_memories_cache: dict[str, MemoryChunk],
        *,
        debug_log: dict[str, dict[str, Any]] | None = None,
    ) -> StageResult:
        """阶段2：向量搜索"""
        start_time = time.time()

        try:
            # 生成查询向量
            query_embedding = await self._generate_query_embedding(query, context, vector_storage)

            if not query_embedding:
                logger.warning("向量搜索阶段：查询向量生成失败")
                return StageResult(
                    stage=RetrievalStage.VECTOR_SEARCH,
                    memory_ids=[],
                    processing_time=time.time() - start_time,
                    filtered_count=0,
                    score_threshold=self.config.vector_similarity_threshold,
                    details=[{"note": "query_embedding_unavailable"}],
                )

            # 执行向量搜索
            search_result = await vector_storage.search_similar_memories(
                query_vector=query_embedding, limit=self.config.vector_search_limit
            )

            if not search_result:
                logger.warning("向量搜索阶段：搜索返回空结果，尝试回退到文本匹配")
                # 向量搜索失败时的回退策略
                return self._create_text_search_fallback(candidate_ids, all_memories_cache, query, start_time)

            candidate_pool = candidate_ids or set(all_memories_cache.keys())

            # 过滤候选记忆
            filtered_memories = []
            details: list[dict[str, Any]] = []
            raw_details: list[dict[str, Any]] = []
            threshold = self.config.vector_similarity_threshold

            for memory_id, similarity in search_result:
                in_metadata_candidates = memory_id in candidate_pool
                above_threshold = similarity >= threshold
                if in_metadata_candidates and above_threshold:
                    filtered_memories.append((memory_id, similarity))

                raw_details.append(
                    {
                        "memory_id": memory_id,
                        "similarity": similarity,
                        "in_metadata": in_metadata_candidates,
                        "above_threshold": above_threshold,
                    }
                )

            # 按相似度排序
            filtered_memories.sort(key=lambda x: x[1], reverse=True)
            result_ids = [memory_id for memory_id, _ in filtered_memories[: self.config.vector_search_limit]]
            kept_ids = set(result_ids)

            for entry in raw_details:
                memory_id = entry["memory_id"]
                similarity = entry["similarity"]
                in_metadata = entry["in_metadata"]
                above_threshold = entry["above_threshold"]

                status = "kept"
                reason = None
                if not in_metadata:
                    status = "excluded"
                    reason = "not_in_metadata_candidates"
                elif not above_threshold:
                    status = "excluded"
                    reason = "below_threshold"
                elif memory_id not in kept_ids:
                    status = "excluded"
                    reason = "limit_pruned"

                detail_entry = {
                    "memory_id": memory_id,
                    "similarity": round(similarity, 4),
                    "status": status,
                    "reason": reason,
                }
                details.append(detail_entry)

                if debug_log is not None:
                    stage_entry = debug_log.setdefault(memory_id, {}).setdefault("vector_stage", {})
                    stage_entry["similarity"] = round(similarity, 4)
                    stage_entry["status"] = status
                    if reason:
                        stage_entry["reason"] = reason

            filtered_count = max(0, len(candidate_pool) - len(result_ids))

            logger.debug(f"向量搜索：{len(candidate_ids)} -> {len(result_ids)} 条记忆")

            return StageResult(
                stage=RetrievalStage.VECTOR_SEARCH,
                memory_ids=result_ids,
                processing_time=time.time() - start_time,
                filtered_count=filtered_count,
                score_threshold=self.config.vector_similarity_threshold,
                details=details,
            )

        except Exception as e:
            logger.error(f"向量搜索阶段失败: {e}")
            return StageResult(
                stage=RetrievalStage.VECTOR_SEARCH,
                memory_ids=[],
                processing_time=time.time() - start_time,
                filtered_count=0,
                score_threshold=self.config.vector_similarity_threshold,
                details=[{"error": str(e)}],
            )

    def _create_text_search_fallback(
        self, candidate_ids: set[str], all_memories_cache: dict[str, MemoryChunk], query_text: str, start_time: float
    ) -> StageResult:
        """当向量搜索失败时，使用文本搜索作为回退策略"""
        try:
            query_lower = query_text.lower()
            query_words = set(query_lower.split())

            text_matches = []
            for memory_id in candidate_ids:
                if memory_id not in all_memories_cache:
                    continue

                memory = all_memories_cache[memory_id]
                memory_text = (memory.display or memory.text_content or "").lower()

                # 简单的文本匹配评分
                word_matches = sum(1 for word in query_words if word in memory_text)
                if word_matches > 0:
                    score = word_matches / len(query_words)
                    text_matches.append((memory_id, score))

            # 按匹配度排序
            text_matches.sort(key=lambda x: x[1], reverse=True)
            result_ids = [memory_id for memory_id, _ in text_matches[: self.config.vector_search_limit]]

            details = []
            for memory_id, score in text_matches[: self.config.vector_search_limit]:
                details.append(
                    {"memory_id": memory_id, "text_match_score": round(score, 4), "status": "text_match_fallback"}
                )

            logger.debug(f"向量搜索回退到文本匹配：找到 {len(result_ids)} 条匹配记忆")

            return StageResult(
                stage=RetrievalStage.VECTOR_SEARCH,
                memory_ids=result_ids,
                processing_time=time.time() - start_time,
                filtered_count=len(candidate_ids) - len(result_ids),
                score_threshold=0.0,  # 文本匹配无严格阈值
                details=details,
            )

        except Exception as e:
            logger.error(f"文本搜索回退失败: {e}")
            return StageResult(
                stage=RetrievalStage.VECTOR_SEARCH,
                memory_ids=list(candidate_ids)[: self.config.vector_search_limit],
                processing_time=time.time() - start_time,
                filtered_count=0,
                score_threshold=0.0,
                details=[{"error": str(e), "note": "text_fallback_failed"}],
            )

    async def _semantic_reranking_stage(
        self,
        query: str,
        user_id: str,
        context: dict[str, Any],
        candidate_ids: set[str],
        all_memories_cache: dict[str, MemoryChunk],
        *,
        debug_log: dict[str, dict[str, Any]] | None = None,
    ) -> StageResult:
        """阶段3：语义重排序"""
        start_time = time.time()

        try:
            reranked_memories = []
            details: list[dict[str, Any]] = []
            threshold = self.config.semantic_similarity_threshold

            for memory_id in candidate_ids:
                if memory_id not in all_memories_cache:
                    continue

                memory = all_memories_cache[memory_id]

                # 计算综合语义相似度
                semantic_score = await self._calculate_semantic_similarity(query, memory, context)

                if semantic_score >= threshold:
                    reranked_memories.append((memory_id, semantic_score))

                status = "kept" if semantic_score >= threshold else "excluded"
                reason = None if status == "kept" else "below_threshold"

                detail_entry = {
                    "memory_id": memory_id,
                    "score": round(semantic_score, 4),
                    "status": status,
                    "reason": reason,
                }
                details.append(detail_entry)

                if debug_log is not None:
                    stage_entry = debug_log.setdefault(memory_id, {}).setdefault("semantic_stage", {})
                    stage_entry["score"] = round(semantic_score, 4)
                    stage_entry["status"] = status
                    if reason:
                        stage_entry["reason"] = reason

            # 按语义相似度排序
            reranked_memories.sort(key=lambda x: x[1], reverse=True)
            result_ids = [memory_id for memory_id, _ in reranked_memories[: self.config.semantic_rerank_limit]]
            kept_ids = set(result_ids)

            filtered_count = len(candidate_ids) - len(result_ids)

            for detail in details:
                if detail["status"] == "kept" and detail["memory_id"] not in kept_ids:
                    detail["status"] = "excluded"
                    detail["reason"] = "limit_pruned"
                    if debug_log is not None:
                        stage_entry = debug_log.setdefault(detail["memory_id"], {}).setdefault("semantic_stage", {})
                        stage_entry["status"] = "excluded"
                        stage_entry["reason"] = "limit_pruned"

            logger.debug(f"语义重排序：{len(candidate_ids)} -> {len(result_ids)} 条记忆")

            return StageResult(
                stage=RetrievalStage.SEMANTIC_RERANKING,
                memory_ids=result_ids,
                processing_time=time.time() - start_time,
                filtered_count=filtered_count,
                score_threshold=self.config.semantic_similarity_threshold,
                details=details,
            )

        except Exception as e:
            logger.error(f"语义重排序阶段失败: {e}")
            return StageResult(
                stage=RetrievalStage.SEMANTIC_RERANKING,
                memory_ids=list(candidate_ids),  # 失败时返回原候选集
                processing_time=time.time() - start_time,
                filtered_count=0,
                score_threshold=self.config.semantic_similarity_threshold,
                details=[{"error": str(e)}],
            )

    async def _contextual_filtering_stage(
        self,
        query: str,
        user_id: str,
        context: dict[str, Any],
        candidate_ids: list[str],
        all_memories_cache: dict[str, MemoryChunk],
        limit: int,
        *,
        debug_log: dict[str, dict[str, Any]] | None = None,
    ) -> StageResult:
        """阶段4：上下文过滤"""
        start_time = time.time()

        try:
            final_memories = []
            details: list[dict[str, Any]] = []

            for memory_id in candidate_ids:
                if memory_id not in all_memories_cache:
                    continue

                memory = all_memories_cache[memory_id]

                # 计算上下文相关度评分
                context_score = await self._calculate_context_relevance(query, memory, context)

                # 结合多因子评分
                final_score = await self._calculate_final_score(query, memory, context, context_score)

                final_memories.append((memory_id, final_score))

                detail_entry = {
                    "memory_id": memory_id,
                    "context_score": round(context_score, 4),
                    "final_score": round(final_score, 4),
                    "status": "candidate",
                }
                details.append(detail_entry)

                if debug_log is not None:
                    stage_entry = debug_log.setdefault(memory_id, {}).setdefault("context_stage", {})
                    stage_entry["context_score"] = round(context_score, 4)
                    stage_entry["final_score"] = round(final_score, 4)

            # 按最终评分排序
            final_memories.sort(key=lambda x: x[1], reverse=True)
            result_ids = [memory_id for memory_id, _ in final_memories[:limit]]
            kept_ids = set(result_ids)

            for detail in details:
                memory_id = detail["memory_id"]
                if memory_id in kept_ids:
                    detail["status"] = "final"
                    if debug_log is not None:
                        stage_entry = debug_log.setdefault(memory_id, {}).setdefault("context_stage", {})
                        stage_entry["status"] = "final"
                else:
                    detail["status"] = "excluded"
                    detail["reason"] = "ranked_out"
                    if debug_log is not None:
                        stage_entry = debug_log.setdefault(memory_id, {}).setdefault("context_stage", {})
                        stage_entry["status"] = "excluded"
                        stage_entry["reason"] = "ranked_out"

            filtered_count = len(candidate_ids) - len(result_ids)

            logger.debug(f"上下文过滤：{len(candidate_ids)} -> {len(result_ids)} 条记忆")

            return StageResult(
                stage=RetrievalStage.CONTEXTUAL_FILTERING,
                memory_ids=result_ids,
                processing_time=time.time() - start_time,
                filtered_count=filtered_count,
                score_threshold=0.0,  # 动态阈值
                details=details,
            )

        except Exception as e:
            logger.error(f"上下文过滤阶段失败: {e}")
            return StageResult(
                stage=RetrievalStage.CONTEXTUAL_FILTERING,
                memory_ids=candidate_ids[:limit],  # 失败时返回前limit个
                processing_time=time.time() - start_time,
                filtered_count=0,
                score_threshold=0.0,
                details=[{"error": str(e)}],
            )

    async def _fallback_retrieval_stage(
        self,
        query: str,
        user_id: str,
        context: dict[str, Any],
        all_memories_cache: dict[str, MemoryChunk],
        limit: int,
        *,
        excluded_ids: set[str] | None = None,
        debug_log: dict[str, dict[str, Any]] | None = None,
    ) -> StageResult:
        """回退检索阶段 - 当主检索失败时使用更宽松的策略"""
        start_time = time.time()

        try:
            excluded_ids = excluded_ids or set()
            fallback_candidates = []

            # 策略1：基于关键词的简单匹配
            query_lower = query.lower()
            query_words = set(query_lower.split())

            for memory_id, memory in all_memories_cache.items():
                if memory_id in excluded_ids:
                    continue

                memory_text = (memory.display or memory.text_content or "").lower()

                # 简单的关键词匹配
                word_matches = sum(1 for word in query_words if word in memory_text)
                if word_matches > 0:
                    score = word_matches / len(query_words)
                    fallback_candidates.append((memory_id, score))

            # 策略2：如果没有关键词匹配，使用时序最近的原则
            if not fallback_candidates:
                logger.debug("关键词匹配无结果，使用时序最近策略")
                recent_memories = sorted(
                    [
                        (mid, mem.metadata.last_accessed or mem.metadata.created_at)
                        for mid, mem in all_memories_cache.items()
                        if mid not in excluded_ids
                    ],
                    key=lambda x: x[1],
                    reverse=True,
                )
                fallback_candidates = [(mid, 0.5) for mid, _ in recent_memories[: limit * 2]]

            # 按分数排序
            fallback_candidates.sort(key=lambda x: x[1], reverse=True)
            result_ids = [memory_id for memory_id, _ in fallback_candidates[:limit]]

            # 记录调试信息
            details = []
            for memory_id, score in fallback_candidates[:limit]:
                detail_entry = {
                    "memory_id": memory_id,
                    "fallback_score": round(score, 4),
                    "status": "fallback_candidate",
                }
                details.append(detail_entry)

                if debug_log is not None:
                    stage_entry = debug_log.setdefault(memory_id, {}).setdefault("fallback_stage", {})
                    stage_entry["score"] = round(score, 4)
                    stage_entry["status"] = "fallback_candidate"

            filtered_count = len(all_memories_cache) - len(result_ids)

            logger.debug(f"回退检索完成：返回 {len(result_ids)} 条记忆")

            return StageResult(
                stage=RetrievalStage.CONTEXTUAL_FILTERING,  # 复用现有枚举
                memory_ids=result_ids,
                processing_time=time.time() - start_time,
                filtered_count=filtered_count,
                score_threshold=0.0,  # 回退机制无阈值
                details=details,
            )

        except Exception as e:
            logger.error(f"回退检索阶段失败: {e}")
            return StageResult(
                stage=RetrievalStage.CONTEXTUAL_FILTERING,
                memory_ids=[],
                processing_time=time.time() - start_time,
                filtered_count=0,
                score_threshold=0.0,
                details=[{"error": str(e)}],
            )

    async def _generate_query_embedding(
        self, query: str, context: dict[str, Any], vector_storage
    ) -> list[float] | None:
        """生成查询向量"""
        try:
            query_plan = context.get("query_plan")
            query_text = query
            if query_plan and getattr(query_plan, "semantic_query", None):
                query_text = query_plan.semantic_query

            if not query_text:
                logger.debug("查询文本为空，无法生成查询向量")
                return None

            if not hasattr(vector_storage, "generate_query_embedding"):
                logger.warning("向量存储对象缺少 generate_query_embedding 方法")
                return None

            logger.debug(f"正在生成查询向量，文本: '{query_text[:100]}'")
            embedding = await vector_storage.generate_query_embedding(query_text)

            if embedding is None:
                logger.warning("向量存储返回空的查询向量")
                return None

            if len(embedding) == 0:
                logger.warning("向量存储返回空列表作为查询向量")
                return None

            logger.debug(f"查询向量生成成功，维度: {len(embedding)}")
            return embedding

        except Exception as e:
            logger.error(f"生成查询向量时发生异常: {e}", exc_info=True)
            return None

    async def _calculate_semantic_similarity(self, query: str, memory: MemoryChunk, context: dict[str, Any]) -> float:
        """计算语义相似度 - 简化优化版本，提升召回率"""
        try:
            query_plan = context.get("query_plan")
            query_text = query
            if query_plan and getattr(query_plan, "semantic_query", None):
                query_text = query_plan.semantic_query

            # 预处理：清理和标准化文本
            memory_text = (memory.display or memory.text_content or "").strip()
            query_text = query_text.strip()

            if not query_text or not memory_text:
                return 0.0

            # 创建小写版本用于匹配
            query_lower = query_text.lower()
            memory_lower = memory_text.lower()

            # 核心匹配策略1：精确子串匹配（最重要）
            exact_score = 0.0
            if query_text in memory_text:
                exact_score = 1.0
            elif query_lower in memory_lower:
                exact_score = 0.9
            elif any(word in memory_lower for word in query_lower.split() if len(word) > 1):
                exact_score = 0.4

            # 核心匹配策略2：词汇匹配
            word_score = 0.0
            try:
                import re

                import jieba

                # 分词处理
                query_words = list(jieba.cut(query_text)) + re.findall(r"[a-zA-Z]+", query_text)
                memory_words = list(jieba.cut(memory_text)) + re.findall(r"[a-zA-Z]+", memory_text)

                # 清理和标准化
                query_words = [w.strip().lower() for w in query_words if w.strip() and len(w.strip()) > 1]
                memory_words = [w.strip().lower() for w in memory_words if w.strip() and len(w.strip()) > 1]

                if query_words and memory_words:
                    query_set = set(query_words)
                    memory_set = set(memory_words)

                    # 精确匹配
                    exact_matches = query_set & memory_set
                    exact_ratio = len(exact_matches) / len(query_set) if query_set else 0

                    # 部分匹配（包含关系）
                    partial_matches = 0
                    for q_word in query_set:
                        if any(q_word in m_word or m_word in q_word for m_word in memory_set if len(q_word) >= 2):
                            partial_matches += 1

                    partial_ratio = partial_matches / len(query_set) if query_set else 0
                    word_score = exact_ratio * 0.8 + partial_ratio * 0.3

            except ImportError:
                # 如果jieba不可用，使用简单分词
                import re

                query_words = re.findall(r"[\w\u4e00-\u9fa5]+", query_lower)
                memory_words = re.findall(r"[\w\u4e00-\u9fa5]+", memory_lower)

                if query_words and memory_words:
                    query_set = set(w for w in query_words if len(w) > 1)
                    memory_set = set(w for w in memory_words if len(w) > 1)

                    if query_set:
                        intersection = query_set & memory_set
                        word_score = len(intersection) / len(query_set)

            # 核心匹配策略3：语义概念匹配
            concept_score = 0.0
            concept_groups = {
                "饮食": ["吃", "饭", "菜", "餐", "饿", "饱", "食", "dinner", "eat", "food", "meal"],
                "天气": ["天气", "阳光", "雨", "晴", "阴", "温度", "weather", "sunny", "rain"],
                "编程": ["编程", "代码", "程序", "开发", "语言", "programming", "code", "develop", "python"],
                "时间": ["今天", "昨天", "明天", "现在", "时间", "today", "yesterday", "tomorrow", "time"],
                "情感": ["好", "坏", "开心", "难过", "有趣", "good", "bad", "happy", "sad", "fun"],
            }

            query_concepts = {
                concept
                for concept, keywords in concept_groups.items()
                if any(keyword in query_lower for keyword in keywords)
            }
            memory_concepts = {
                concept
                for concept, keywords in concept_groups.items()
                if any(keyword in memory_lower for keyword in keywords)
            }

            if query_concepts and memory_concepts:
                concept_overlap = query_concepts & memory_concepts
                concept_score = len(concept_overlap) / len(query_concepts) * 0.5

            # 核心匹配策略4：查询计划增强
            plan_bonus = 0.0
            if query_plan:
                # 主体匹配
                if hasattr(query_plan, "subjects") and query_plan.subjects:
                    for subject in query_plan.subjects:
                        if subject.lower() in memory_lower:
                            plan_bonus += 0.15

                # 对象匹配
                if hasattr(query_plan, "objects") and query_plan.objects:
                    for obj in query_plan.objects:
                        if obj.lower() in memory_lower:
                            plan_bonus += 0.1

                # 记忆类型匹配
                if hasattr(query_plan, "memory_types") and query_plan.memory_types:
                    if memory.memory_type in query_plan.memory_types:
                        plan_bonus += 0.1

            # 综合评分计算 - 简化权重分配
            if exact_score >= 0.9:
                # 精确匹配为主
                final_score = exact_score * 0.6 + word_score * 0.2 + concept_score + plan_bonus
            else:
                # 综合评分
                final_score = exact_score * 0.3 + word_score * 0.3 + concept_score + plan_bonus

            # 基础分数保障：避免过低分数
            if final_score > 0:
                if exact_score > 0 or word_score > 0.1:
                    final_score = max(final_score, 0.1)  # 有实际匹配的最小分数
                else:
                    final_score = max(final_score, 0.05)  # 仅概念匹配的最小分数

            # 确保分数在合理范围
            final_score = min(1.0, max(0.0, final_score))

            return final_score

        except Exception as e:
            logger.warning(f"计算语义相似度失败: {e}")
            return 0.0

    async def _calculate_context_relevance(self, query: str, memory: MemoryChunk, context: dict[str, Any]) -> float:
        """计算上下文相关度"""
        try:
            score = 0.0

            query_plan = context.get("query_plan")

            # 检查记忆类型是否匹配上下文
            if context.get("expected_memory_types"):
                if memory.memory_type in context["expected_memory_types"]:
                    score += 0.3
            elif query_plan and getattr(query_plan, "memory_types", None):
                if memory.memory_type in query_plan.memory_types:
                    score += 0.3

            # 检查关键词匹配
            if context.get("keywords"):
                memory_keywords = set(memory.keywords)
                context_keywords = set(context["keywords"])
                overlap = memory_keywords & context_keywords
                if overlap:
                    score += len(overlap) / max(len(context_keywords), 1) * 0.4

            if query_plan:
                # 主体匹配
                subject_score = self._calculate_subject_overlap(memory, getattr(query_plan, "subject_includes", []))
                score += subject_score * 0.3

                # 对象/描述匹配
                object_keywords = getattr(query_plan, "object_includes", []) or []
                if object_keywords:
                    display_text = (memory.display or memory.text_content or "").lower()
                    hits = sum(
                        1
                        for kw in object_keywords
                        if isinstance(kw, str) and kw.strip() and kw.strip().lower() in display_text
                    )
                    if hits:
                        score += min(0.3, hits * 0.1)

                optional_keywords = getattr(query_plan, "optional_keywords", []) or []
                if optional_keywords:
                    display_text = (memory.display or memory.text_content or "").lower()
                    hits = sum(
                        1
                        for kw in optional_keywords
                        if isinstance(kw, str) and kw.strip() and kw.strip().lower() in display_text
                    )
                    if hits:
                        score += min(0.2, hits * 0.05)

                # 时间偏好
                recency_pref = getattr(query_plan, "recency_preference", "")
                if recency_pref:
                    memory_age = time.time() - memory.metadata.created_at
                    if recency_pref == "recent" and memory_age < 7 * 24 * 3600:
                        score += 0.2
                    elif recency_pref == "historical" and memory_age > 30 * 24 * 3600:
                        score += 0.1

            # 检查时效性
            if context.get("recent_only", False):
                memory_age = time.time() - memory.metadata.created_at
                if memory_age < 7 * 24 * 3600:  # 7天内
                    score += 0.3

            return min(score, 1.0)

        except Exception as e:
            logger.warning(f"计算上下文相关度失败: {e}")
            return 0.0

    async def _calculate_final_score(
        self, query: str, memory: MemoryChunk, context: dict[str, Any], context_score: float
    ) -> float:
        """计算最终评分"""
        try:
            query_plan = context.get("query_plan")

            # 语义相似度
            semantic_score = await self._calculate_semantic_similarity(query, memory, context)

            # 向量相似度（如果有）
            vector_score = 0.0
            if memory.embedding:
                # 这里应该有向量相似度计算，简化处理
                vector_score = 0.5

            # 时效性评分
            recency_score = self._calculate_recency_score(memory.metadata.created_at)
            if query_plan:
                recency_pref = getattr(query_plan, "recency_preference", "")
                if recency_pref == "recent":
                    recency_score = max(recency_score, 0.8)
                elif recency_pref == "historical":
                    recency_score = min(recency_score, 0.5)

            # 权重组合
            vector_weight = self.config.vector_weight
            semantic_weight = self.config.semantic_weight
            context_weight = self.config.context_weight
            recency_weight = self.config.recency_weight

            if query_plan and getattr(query_plan, "emphasis", None) == "precision":
                semantic_weight += 0.05
            elif query_plan and getattr(query_plan, "emphasis", None) == "recall":
                context_weight += 0.05

            final_score = (
                semantic_score * semantic_weight
                + vector_score * vector_weight
                + context_score * context_weight
                + recency_score * recency_weight
            )

            # 加入记忆重要性权重
            importance_weight = memory.metadata.importance.value / 4.0  # 标准化到0-1
            final_score = final_score * (0.7 + importance_weight * 0.3)  # 重要性影响30%

            return final_score

        except Exception as e:
            logger.warning(f"计算最终评分失败: {e}")
            return 0.0

    def _calculate_subject_overlap(self, memory: MemoryChunk, required_subjects: list[str] | None) -> float:
        if not required_subjects:
            return 0.0

        memory_subjects = {subject.lower() for subject in memory.subjects if isinstance(subject, str)}
        if not memory_subjects:
            return 0.0

        hit = 0
        total = 0
        for subject in required_subjects:
            if not isinstance(subject, str):
                continue
            total += 1
            normalized = subject.strip().lower()
            if not normalized:
                continue
            if any(normalized in mem_subject for mem_subject in memory_subjects):
                hit += 1

        if total == 0:
            return 0.0

        return hit / total

    def _calculate_recency_score(self, timestamp: float) -> float:
        """计算时效性评分"""
        try:
            age = time.time() - timestamp
            age_days = age / (24 * 3600)

            if age_days < 1:
                return 1.0
            elif age_days < 7:
                return 0.8
            elif age_days < 30:
                return 0.6
            elif age_days < 90:
                return 0.4
            else:
                return 0.2

        except Exception:
            return 0.5

    def _extract_memory_types_from_context(self, context: dict[str, Any]) -> list[MemoryType]:
        """从上下文中提取记忆类型"""
        try:
            query_plan = context.get("query_plan")
            if query_plan and getattr(query_plan, "memory_types", None):
                return query_plan.memory_types

            if "expected_memory_types" in context:
                return context["expected_memory_types"]

            # 根据上下文推断记忆类型
            if "message_type" in context:
                message_type = context["message_type"]
                if message_type in ["personal_info", "fact"]:
                    return [MemoryType.PERSONAL_FACT]
                elif message_type in ["event", "activity"]:
                    return [MemoryType.EVENT]
                elif message_type in ["preference", "like"]:
                    return [MemoryType.PREFERENCE]
                elif message_type in ["opinion", "view"]:
                    return [MemoryType.OPINION]

            return []

        except Exception:
            return []

    def _extract_keywords_from_query(self, query: str, query_plan: Any | None = None) -> list[str]:
        """从查询中提取关键词"""
        try:
            extracted: list[str] = []

            if query_plan and getattr(query_plan, "required_keywords", None):
                extracted.extend([kw.lower() for kw in query_plan.required_keywords if isinstance(kw, str)])

            # 简单的关键词提取
            words = query.lower().split()
            # 过滤停用词
            stopwords = {"的", "是", "在", "有", "我", "你", "他", "她", "它", "这", "那", "了", "吗", "呢"}
            extracted.extend(word for word in words if len(word) > 1 and word not in stopwords)

            # 去重并保留顺序
            seen = set()
            deduplicated = []
            for word in extracted:
                if word in seen or not word:
                    continue
                seen.add(word)
                deduplicated.append(word)

            return deduplicated[:10]
        except Exception:
            return []

    def _update_retrieval_stats(self, total_time: float, stage_results: list[StageResult]):
        """更新检索统计"""
        self.retrieval_stats["total_queries"] += 1

        # 更新平均检索时间
        current_avg = self.retrieval_stats["average_retrieval_time"]
        total_queries = self.retrieval_stats["total_queries"]
        new_avg = (current_avg * (total_queries - 1) + total_time) / total_queries
        self.retrieval_stats["average_retrieval_time"] = new_avg

        # 更新各阶段统计
        for result in stage_results:
            stage_name = result.stage.value
            if stage_name in self.retrieval_stats["stage_stats"]:
                stage_stat = self.retrieval_stats["stage_stats"][stage_name]
                stage_stat["calls"] += 1

                current_stage_avg = stage_stat["avg_time"]
                new_stage_avg = (current_stage_avg * (stage_stat["calls"] - 1) + result.processing_time) / stage_stat[
                    "calls"
                ]
                stage_stat["avg_time"] = new_stage_avg

    def get_retrieval_stats(self) -> dict[str, Any]:
        """获取检索统计信息"""
        return self.retrieval_stats.copy()

    def reset_stats(self):
        """重置统计信息"""
        self.retrieval_stats = {
            "total_queries": 0,
            "average_retrieval_time": 0.0,
            "stage_stats": {
                "metadata_filtering": {"calls": 0, "avg_time": 0.0},
                "vector_search": {"calls": 0, "avg_time": 0.0},
                "semantic_reranking": {"calls": 0, "avg_time": 0.0},
                "contextual_filtering": {"calls": 0, "avg_time": 0.0},
                "enhanced_reranking": {"calls": 0, "avg_time": 0.0},
            },
        }

    async def _enhanced_reranking_stage(
        self,
        query: str,
        user_id: str,
        context: dict[str, Any],
        candidate_ids: list[str],
        all_memories_cache: dict[str, MemoryChunk],
        limit: int,
        *,
        debug_log: dict[str, dict[str, Any]] | None = None,
    ) -> StageResult:
        """阶段5：增强重排序 - 使用多维度评分模型"""
        start_time = time.time()

        try:
            if not candidate_ids:
                return StageResult(
                    stage=RetrievalStage.CONTEXTUAL_FILTERING,  # 保持与原有枚举兼容
                    memory_ids=[],
                    processing_time=time.time() - start_time,
                    filtered_count=0,
                    score_threshold=0.0,
                    details=[{"note": "no_candidates"}],
                )

            # 准备候选记忆数据
            candidate_memories = []
            for memory_id in candidate_ids:
                memory = all_memories_cache.get(memory_id)
                if memory:
                    # 使用原始向量相似度作为基础分数
                    vector_similarity = 0.8  # 默认分数，实际应该从前面阶段传递
                    candidate_memories.append((memory_id, memory, vector_similarity))

            if not candidate_memories:
                return StageResult(
                    stage=RetrievalStage.CONTEXTUAL_FILTERING,
                    memory_ids=[],
                    processing_time=time.time() - start_time,
                    filtered_count=len(candidate_ids),
                    score_threshold=0.0,
                    details=[{"note": "candidates_not_found_in_cache"}],
                )

            # 使用增强重排序器
            reranked_memories = self.reranker.rerank_memories(
                query=query, candidate_memories=candidate_memories, context=context, limit=limit
            )

            # 提取重排序后的记忆ID
            result_ids = [memory_id for memory_id, _, _ in reranked_memories]

            # 生成调试详情
            details = []
            for memory_id, memory, final_score in reranked_memories:
                detail_entry = {
                    "memory_id": memory_id,
                    "final_score": round(final_score, 4),
                    "status": "reranked",
                    "memory_type": memory.memory_type.value,
                    "access_count": memory.metadata.access_count,
                }
                details.append(detail_entry)

                if debug_log is not None:
                    stage_entry = debug_log.setdefault(memory_id, {}).setdefault("enhanced_rerank_stage", {})
                    stage_entry["final_score"] = round(final_score, 4)
                    stage_entry["status"] = "reranked"
                    stage_entry["rank"] = len(details)

            # 记录被过滤的记忆
            kept_ids = set(result_ids)
            for memory_id in candidate_ids:
                if memory_id not in kept_ids:
                    detail_entry = {"memory_id": memory_id, "status": "filtered_out", "reason": "ranked_below_limit"}
                    details.append(detail_entry)

                    if debug_log is not None:
                        stage_entry = debug_log.setdefault(memory_id, {}).setdefault("enhanced_rerank_stage", {})
                        stage_entry["status"] = "filtered_out"
                        stage_entry["reason"] = "ranked_below_limit"

            filtered_count = len(candidate_ids) - len(result_ids)

            logger.debug(f"增强重排序完成：候选={len(candidate_ids)}, 返回={len(result_ids)}, 过滤={filtered_count}")

            return StageResult(
                stage=RetrievalStage.CONTEXTUAL_FILTERING,  # 保持与原有枚举兼容
                memory_ids=result_ids,
                processing_time=time.time() - start_time,
                filtered_count=filtered_count,
                score_threshold=0.0,  # 动态阈值，由重排序器决定
                details=details,
            )

        except Exception as e:
            logger.error(f"增强重排序阶段失败: {e}", exc_info=True)
            return StageResult(
                stage=RetrievalStage.CONTEXTUAL_FILTERING,
                memory_ids=candidate_ids[:limit],  # 失败时返回前limit个
                processing_time=time.time() - start_time,
                filtered_count=0,
                score_threshold=0.0,
                details=[{"error": str(e)}],
            )
