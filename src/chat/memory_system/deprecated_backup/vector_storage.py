"""
向量数据库存储接口
为记忆系统提供高效的向量存储和语义搜索能力
"""

import asyncio
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import orjson

from src.chat.memory_system.memory_chunk import MemoryChunk
from src.common.config_helpers import resolve_embedding_dimension
from src.common.logger import get_logger
from src.config.config import model_config
from src.llm_models.utils_model import LLMRequest

logger = get_logger(__name__)

# 尝试导入FAISS，如果不可用则使用简单替代
try:
    import faiss

    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    logger.warning("FAISS not available, using simple vector storage")


@dataclass
class VectorStorageConfig:
    """向量存储配置"""

    dimension: int = 1024
    similarity_threshold: float = 0.8
    index_type: str = "flat"  # flat, ivf, hnsw
    max_index_size: int = 100000
    storage_path: str = "data/memory_vectors"
    auto_save_interval: int = 10  # 每N次操作自动保存
    enable_compression: bool = True


class VectorStorageManager:
    """向量存储管理器"""

    def __init__(self, config: VectorStorageConfig | None = None):
        self.config = config or VectorStorageConfig()

        resolved_dimension = resolve_embedding_dimension(self.config.dimension)
        if resolved_dimension and resolved_dimension != self.config.dimension:
            logger.info(
                "向量存储维度调整: 使用嵌入模型配置的维度 %d (原始配置: %d)",
                resolved_dimension,
                self.config.dimension,
            )
            self.config.dimension = resolved_dimension
        self.storage_path = Path(self.config.storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # 向量索引
        self.vector_index = None
        self.memory_id_to_index = {}  # memory_id -> vector index
        self.index_to_memory_id = {}  # vector index -> memory_id

        # 内存缓存
        self.memory_cache: dict[str, MemoryChunk] = {}
        self.vector_cache: dict[str, list[float]] = {}

        # 统计信息
        self.storage_stats = {
            "total_vectors": 0,
            "index_build_time": 0.0,
            "average_search_time": 0.0,
            "cache_hit_rate": 0.0,
            "total_searches": 0,
            "cache_hits": 0,
        }

        # 线程锁
        self._lock = threading.RLock()
        self._operation_count = 0

        # 初始化索引
        self._initialize_index()

        # 嵌入模型
        self.embedding_model: LLMRequest = None

    def _initialize_index(self):
        """初始化向量索引"""
        try:
            if FAISS_AVAILABLE:
                if self.config.index_type == "flat":
                    self.vector_index = faiss.IndexFlatIP(self.config.dimension)
                elif self.config.index_type == "ivf":
                    quantizer = faiss.IndexFlatIP(self.config.dimension)
                    nlist = min(100, max(1, self.config.max_index_size // 1000))
                    self.vector_index = faiss.IndexIVFFlat(quantizer, self.config.dimension, nlist)
                elif self.config.index_type == "hnsw":
                    self.vector_index = faiss.IndexHNSWFlat(self.config.dimension, 32)
                    self.vector_index.hnsw.efConstruction = 40
                else:
                    self.vector_index = faiss.IndexFlatIP(self.config.dimension)
            else:
                # 简单的向量存储实现
                self.vector_index = SimpleVectorIndex(self.config.dimension)

            logger.info(f"✅ 向量索引初始化完成，类型: {self.config.index_type}")

        except Exception as e:
            logger.error(f"❌ 向量索引初始化失败: {e}")
            # 回退到简单实现
            self.vector_index = SimpleVectorIndex(self.config.dimension)

    async def initialize_embedding_model(self):
        """初始化嵌入模型"""
        if self.embedding_model is None:
            self.embedding_model = LLMRequest(
                model_set=model_config.model_task_config.embedding, request_type="memory.embedding"
            )
            logger.info("✅ 嵌入模型初始化完成")

    async def generate_query_embedding(self, query_text: str) -> list[float] | None:
        """生成查询向量，用于记忆召回"""
        if not query_text:
            logger.warning("查询文本为空，无法生成向量")
            return None

        try:
            await self.initialize_embedding_model()

            logger.debug(f"开始生成查询向量，文本: '{query_text[:50]}{'...' if len(query_text) > 50 else ''}'")

            embedding, _ = await self.embedding_model.get_embedding(query_text)
            if not embedding:
                logger.warning("嵌入模型返回空向量")
                return None

            logger.debug(f"生成的向量维度: {len(embedding)}, 期望维度: {self.config.dimension}")

            if len(embedding) != self.config.dimension:
                logger.error("查询向量维度不匹配: 期望 %d, 实际 %d", self.config.dimension, len(embedding))
                return None

            normalized_vector = self._normalize_vector(embedding)
            logger.debug(f"查询向量生成成功，向量范围: [{min(normalized_vector):.4f}, {max(normalized_vector):.4f}]")
            return normalized_vector

        except Exception as exc:
            logger.error(f"❌ 生成查询向量失败: {exc}", exc_info=True)
            return None

    async def store_memories(self, memories: list[MemoryChunk]):
        """存储记忆向量"""
        if not memories:
            return

        start_time = time.time()

        try:
            # 确保嵌入模型已初始化
            await self.initialize_embedding_model()

            # 批量获取嵌入向量
            memory_texts = []

            for memory in memories:
                # 预先缓存记忆，确保后续流程可访问
                self.memory_cache[memory.memory_id] = memory
                if memory.embedding is None:
                    # 如果没有嵌入向量，需要生成
                    text = self._prepare_embedding_text(memory)
                    memory_texts.append((memory.memory_id, text))
                else:
                    # 已有嵌入向量，直接使用
                    await self._add_single_memory(memory, memory.embedding)

            # 批量生成缺失的嵌入向量
            if memory_texts:
                await self._batch_generate_and_store_embeddings(memory_texts)

            # 自动保存检查
            self._operation_count += len(memories)
            if self._operation_count >= self.config.auto_save_interval:
                await self.save_storage()
                self._operation_count = 0

            storage_time = time.time() - start_time
            logger.debug(f"向量存储完成，{len(memories)} 条记忆，耗时 {storage_time:.3f}秒")

        except Exception as e:
            logger.error(f"❌ 向量存储失败: {e}", exc_info=True)

    def _prepare_embedding_text(self, memory: MemoryChunk) -> str:
        """准备用于嵌入的文本，仅使用自然语言展示内容"""
        display_text = (memory.display or "").strip()
        if display_text:
            return display_text

        fallback_text = (memory.text_content or "").strip()
        if fallback_text:
            return fallback_text

        subjects = "、".join(s.strip() for s in memory.subjects if s and isinstance(s, str))
        predicate = (memory.content.predicate or "").strip()

        obj = memory.content.object
        if isinstance(obj, dict):
            object_parts = []
            for key, value in obj.items():
                if value is None:
                    continue
                if isinstance(value, (list, tuple)):
                    preview = "、".join(str(item) for item in value[:3])
                    object_parts.append(f"{key}:{preview}")
                else:
                    object_parts.append(f"{key}:{value}")
            object_text = ", ".join(object_parts)
        else:
            object_text = str(obj or "").strip()

        composite_parts = [part for part in [subjects, predicate, object_text] if part]
        if composite_parts:
            return " ".join(composite_parts)

        logger.debug("记忆 %s 缺少可用展示文本，使用占位符生成嵌入输入", memory.memory_id)
        return memory.memory_id

    async def _batch_generate_and_store_embeddings(self, memory_texts: list[tuple[str, str]]):
        """批量生成和存储嵌入向量"""
        if not memory_texts:
            return

        try:
            texts = [text for _, text in memory_texts]
            memory_ids = [memory_id for memory_id, _ in memory_texts]

            # 批量生成嵌入向量
            embeddings = await self._batch_generate_embeddings(memory_ids, texts)

            # 存储向量和记忆
            for memory_id, embedding in embeddings.items():
                if embedding and len(embedding) == self.config.dimension:
                    memory = self.memory_cache.get(memory_id)
                    if memory:
                        await self._add_single_memory(memory, embedding)

        except Exception as e:
            logger.error(f"❌ 批量生成嵌入向量失败: {e}")

    async def _batch_generate_embeddings(self, memory_ids: list[str], texts: list[str]) -> dict[str, list[float]]:
        """批量生成嵌入向量"""
        if not texts:
            return {}

        results: dict[str, list[float]] = {}

        try:
            semaphore = asyncio.Semaphore(min(4, max(1, len(texts))))

            async def generate_embedding(memory_id: str, text: str) -> None:
                async with semaphore:
                    try:
                        embedding, _ = await self.embedding_model.get_embedding(text)
                        if embedding and len(embedding) == self.config.dimension:
                            results[memory_id] = embedding
                        else:
                            logger.warning(
                                "嵌入向量维度不匹配: 期望 %d, 实际 %d (memory_id=%s)。请检查模型嵌入配置 model_config.model_task_config.embedding.embedding_dimension 或 LPMM 任务定义。",
                                self.config.dimension,
                                len(embedding) if embedding else 0,
                                memory_id,
                            )
                            results[memory_id] = []
                    except Exception as exc:
                        logger.warning("生成记忆 %s 的嵌入向量失败: %s", memory_id, exc)
                        results[memory_id] = []

            tasks = [
                asyncio.create_task(generate_embedding(mid, text)) for mid, text in zip(memory_ids, texts, strict=False)
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            logger.error(f"❌ 批量生成嵌入向量失败: {e}")
            for memory_id in memory_ids:
                results.setdefault(memory_id, [])

        return results

    async def _add_single_memory(self, memory: MemoryChunk, embedding: list[float]):
        """添加单个记忆到向量存储"""
        with self._lock:
            try:
                # 规范化向量
                if embedding:
                    embedding = self._normalize_vector(embedding)

                # 添加到缓存
                self.memory_cache[memory.memory_id] = memory
                self.vector_cache[memory.memory_id] = embedding

                # 更新记忆的嵌入向量
                memory.set_embedding(embedding)

                # 添加到向量索引
                if hasattr(self.vector_index, "add"):
                    # FAISS索引
                    if isinstance(embedding, np.ndarray):
                        vector_array = embedding.reshape(1, -1).astype("float32")
                    else:
                        vector_array = np.array([embedding], dtype="float32")

                    # 特殊处理IVF索引
                    if self.config.index_type == "ivf" and self.vector_index.ntotal == 0:
                        # IVF索引需要先训练
                        logger.debug("训练IVF索引...")
                        self.vector_index.train(vector_array)

                    self.vector_index.add(vector_array)
                    index_id = self.vector_index.ntotal - 1

                else:
                    # 简单索引
                    index_id = self.vector_index.add_vector(embedding)

                # 更新映射关系
                self.memory_id_to_index[memory.memory_id] = index_id
                self.index_to_memory_id[index_id] = memory.memory_id

                # 更新统计
                self.storage_stats["total_vectors"] += 1

            except Exception as e:
                logger.error(f"❌ 添加记忆到向量存储失败: {e}")

    def _normalize_vector(self, vector: list[float]) -> list[float]:
        """L2归一化向量"""
        if not vector:
            return vector

        try:
            vector_array = np.array(vector, dtype=np.float32)
            norm = np.linalg.norm(vector_array)
            if norm == 0:
                return vector

            normalized = vector_array / norm
            return normalized.tolist()

        except Exception as e:
            logger.warning(f"向量归一化失败: {e}")
            return vector

    async def search_similar_memories(
        self,
        query_vector: list[float] | None = None,
        *,
        query_text: str | None = None,
        limit: int = 10,
        scope_id: str | None = None,
    ) -> list[tuple[str, float]]:
        """搜索相似记忆"""
        start_time = time.time()

        try:
            logger.debug(f"开始向量搜索: query_text='{query_text[:30] if query_text else 'None'}', limit={limit}")

            if query_vector is None:
                if not query_text:
                    logger.warning("查询向量和查询文本都为空")
                    return []

                query_vector = await self.generate_query_embedding(query_text)
                if not query_vector:
                    logger.warning("查询向量生成失败")
                    return []

            scope_filter: str | None = None
            if isinstance(scope_id, str):
                normalized_scope = scope_id.strip().lower()
                if normalized_scope and normalized_scope not in {"global", "global_memory"}:
                    scope_filter = scope_id
            elif scope_id:
                scope_filter = str(scope_id)

            # 规范化查询向量
            query_vector = self._normalize_vector(query_vector)

            logger.debug(f"查询向量维度: {len(query_vector)}, 存储总向量数: {self.storage_stats['total_vectors']}")

            # 检查向量索引状态
            if not self.vector_index:
                logger.error("向量索引未初始化")
                return []

            total_vectors = 0
            if hasattr(self.vector_index, "ntotal"):
                total_vectors = self.vector_index.ntotal
            elif hasattr(self.vector_index, "vectors"):
                total_vectors = len(self.vector_index.vectors)

            logger.debug(f"向量索引中实际向量数: {total_vectors}")

            if total_vectors == 0:
                logger.warning("向量索引为空，无法执行搜索")
                return []

            # 执行向量搜索
            with self._lock:
                if hasattr(self.vector_index, "search"):
                    # FAISS索引
                    if isinstance(query_vector, np.ndarray):
                        query_array = query_vector.reshape(1, -1).astype("float32")
                    else:
                        query_array = np.array([query_vector], dtype="float32")

                    if self.config.index_type == "ivf" and self.vector_index.ntotal > 0:
                        # 设置IVF搜索参数
                        nprobe = min(self.vector_index.nlist, 10)
                        self.vector_index.nprobe = nprobe
                        logger.debug(f"IVF搜索参数: nprobe={nprobe}")

                    search_limit = min(limit, total_vectors)
                    logger.debug(f"执行FAISS搜索，搜索限制: {search_limit}")

                    distances, indices = self.vector_index.search(query_array, search_limit)
                    distances = distances.flatten().tolist()
                    indices = indices.flatten().tolist()

                    logger.debug(f"FAISS搜索结果: {len(distances)} 个距离值, {len(indices)} 个索引")
                else:
                    # 简单索引
                    logger.debug("使用简单向量索引执行搜索")
                    results = self.vector_index.search(query_vector, limit)
                    distances = [score for _, score in results]
                    indices = [idx for idx, _ in results]
                    logger.debug(f"简单索引搜索结果: {len(results)} 个结果")

            # 处理搜索结果
            results = []
            valid_results = 0
            invalid_indices = 0
            filtered_by_scope = 0

            for distance, index in zip(distances, indices, strict=False):
                if index == -1:  # FAISS的无效索引标记
                    invalid_indices += 1
                    continue

                memory_id = self.index_to_memory_id.get(index)
                if not memory_id:
                    logger.debug(f"索引 {index} 没有对应的记忆ID")
                    invalid_indices += 1
                    continue

                if scope_filter:
                    memory = self.memory_cache.get(memory_id)
                    if memory and str(memory.user_id) != scope_filter:
                        filtered_by_scope += 1
                        continue

                similarity = max(0.0, min(1.0, distance))  # 确保在0-1范围内
                results.append((memory_id, similarity))
                valid_results += 1

            logger.debug(
                f"搜索结果处理: 总距离={len(distances)}, 有效结果={valid_results}, "
                f"无效索引={invalid_indices}, 作用域过滤={filtered_by_scope}"
            )

            # 更新统计
            search_time = time.time() - start_time
            self.storage_stats["total_searches"] += 1
            self.storage_stats["average_search_time"] = (
                self.storage_stats["average_search_time"] * (self.storage_stats["total_searches"] - 1) + search_time
            ) / self.storage_stats["total_searches"]

            final_results = results[:limit]
            logger.info(
                f"向量搜索完成: 查询='{query_text[:20] if query_text else 'vector'}' "
                f"耗时={search_time:.3f}s, 返回={len(final_results)}个结果"
            )

            return final_results

        except Exception as e:
            logger.error(f"❌ 向量搜索失败: {e}", exc_info=True)
            return []

    async def get_memory_by_id(self, memory_id: str) -> MemoryChunk | None:
        """根据ID获取记忆"""
        # 先检查缓存
        if memory_id in self.memory_cache:
            self.storage_stats["cache_hits"] += 1
            return self.memory_cache[memory_id]

        self.storage_stats["total_searches"] += 1
        return None

    async def update_memory_embedding(self, memory_id: str, new_embedding: list[float]):
        """更新记忆的嵌入向量"""
        with self._lock:
            try:
                if memory_id not in self.memory_id_to_index:
                    logger.warning(f"记忆 {memory_id} 不存在于向量索引中")
                    return

                # 获取旧索引
                old_index = self.memory_id_to_index[memory_id]

                # 删除旧向量（如果支持）
                if hasattr(self.vector_index, "remove_ids"):
                    try:
                        self.vector_index.remove_ids(np.array([old_index]))
                    except:
                        logger.warning("无法删除旧向量，将直接添加新向量")

                # 规范化新向量
                new_embedding = self._normalize_vector(new_embedding)

                # 添加新向量
                if hasattr(self.vector_index, "add"):
                    if isinstance(new_embedding, np.ndarray):
                        vector_array = new_embedding.reshape(1, -1).astype("float32")
                    else:
                        vector_array = np.array([new_embedding], dtype="float32")

                    self.vector_index.add(vector_array)
                    new_index = self.vector_index.ntotal - 1
                else:
                    new_index = self.vector_index.add_vector(new_embedding)

                # 更新映射关系
                self.memory_id_to_index[memory_id] = new_index
                self.index_to_memory_id[new_index] = memory_id

                # 更新缓存
                self.vector_cache[memory_id] = new_embedding

                # 更新记忆对象
                memory = self.memory_cache.get(memory_id)
                if memory:
                    memory.set_embedding(new_embedding)

                logger.debug(f"更新记忆 {memory_id} 的嵌入向量")

            except Exception as e:
                logger.error(f"❌ 更新记忆嵌入向量失败: {e}")

    async def delete_memory(self, memory_id: str):
        """删除记忆"""
        with self._lock:
            try:
                if memory_id not in self.memory_id_to_index:
                    return

                # 获取索引
                index = self.memory_id_to_index[memory_id]

                # 从向量索引中删除（如果支持）
                if hasattr(self.vector_index, "remove_ids"):
                    try:
                        self.vector_index.remove_ids(np.array([index]))
                    except:
                        logger.warning("无法从向量索引中删除，仅从缓存中移除")

                # 删除映射关系
                del self.memory_id_to_index[memory_id]
                if index in self.index_to_memory_id:
                    del self.index_to_memory_id[index]

                # 从缓存中删除
                self.memory_cache.pop(memory_id, None)
                self.vector_cache.pop(memory_id, None)

                # 更新统计
                self.storage_stats["total_vectors"] = max(0, self.storage_stats["total_vectors"] - 1)

                logger.debug(f"删除记忆 {memory_id}")

            except Exception as e:
                logger.error(f"❌ 删除记忆失败: {e}")

    async def save_storage(self):
        """保存向量存储到文件"""
        try:
            logger.info("正在保存向量存储...")

            # 保存记忆缓存
            cache_data = {memory_id: memory.to_dict() for memory_id, memory in self.memory_cache.items()}

            cache_file = self.storage_path / "memory_cache.json"
            with open(cache_file, "w", encoding="utf-8") as f:
                f.write(orjson.dumps(cache_data, option=orjson.OPT_INDENT_2).decode("utf-8"))

            # 保存向量缓存
            vector_cache_file = self.storage_path / "vector_cache.json"
            with open(vector_cache_file, "w", encoding="utf-8") as f:
                f.write(orjson.dumps(self.vector_cache, option=orjson.OPT_INDENT_2).decode("utf-8"))

            # 保存映射关系
            mapping_file = self.storage_path / "id_mapping.json"
            mapping_data = {
                "memory_id_to_index": {
                    str(memory_id): int(index) for memory_id, index in self.memory_id_to_index.items()
                },
                "index_to_memory_id": {str(index): memory_id for index, memory_id in self.index_to_memory_id.items()},
            }
            with open(mapping_file, "w", encoding="utf-8") as f:
                f.write(orjson.dumps(mapping_data, option=orjson.OPT_INDENT_2).decode("utf-8"))

            # 保存FAISS索引（如果可用）
            if FAISS_AVAILABLE and hasattr(self.vector_index, "save"):
                index_file = self.storage_path / "vector_index.faiss"
                faiss.write_index(self.vector_index, str(index_file))

            # 保存统计信息
            stats_file = self.storage_path / "storage_stats.json"
            with open(stats_file, "w", encoding="utf-8") as f:
                f.write(orjson.dumps(self.storage_stats, option=orjson.OPT_INDENT_2).decode("utf-8"))

            logger.info("✅ 向量存储保存完成")

        except Exception as e:
            logger.error(f"❌ 保存向量存储失败: {e}")

    async def load_storage(self):
        """从文件加载向量存储"""
        try:
            logger.info("正在加载向量存储...")

            # 加载记忆缓存
            cache_file = self.storage_path / "memory_cache.json"
            if cache_file.exists():
                with open(cache_file, encoding="utf-8") as f:
                    cache_data = orjson.loads(f.read())

                self.memory_cache = {
                    memory_id: MemoryChunk.from_dict(memory_data) for memory_id, memory_data in cache_data.items()
                }

            # 加载向量缓存
            vector_cache_file = self.storage_path / "vector_cache.json"
            if vector_cache_file.exists():
                with open(vector_cache_file, encoding="utf-8") as f:
                    self.vector_cache = orjson.loads(f.read())

            # 加载映射关系
            mapping_file = self.storage_path / "id_mapping.json"
            if mapping_file.exists():
                with open(mapping_file, encoding="utf-8") as f:
                    mapping_data = orjson.loads(f.read())
                raw_memory_to_index = mapping_data.get("memory_id_to_index", {})
                self.memory_id_to_index = {
                    str(memory_id): int(index) for memory_id, index in raw_memory_to_index.items()
                }

                raw_index_to_memory = mapping_data.get("index_to_memory_id", {})
                self.index_to_memory_id = {int(index): memory_id for index, memory_id in raw_index_to_memory.items()}

            # 加载FAISS索引（如果可用）
            index_loaded = False
            if FAISS_AVAILABLE:
                index_file = self.storage_path / "vector_index.faiss"
                if index_file.exists():
                    try:
                        loaded_index = faiss.read_index(str(index_file))
                        # 如果索引类型匹配，则替换
                        if type(loaded_index) == type(self.vector_index):
                            self.vector_index = loaded_index
                            index_loaded = True
                            logger.info("✅ FAISS索引文件加载完成")
                        else:
                            logger.warning("索引类型不匹配，重新构建索引")
                    except Exception as e:
                        logger.warning(f"加载FAISS索引失败: {e}，重新构建")
                else:
                    logger.info("FAISS索引文件不存在，将重新构建")

                # 如果索引没有成功加载且有向量数据，则重建索引
                if not index_loaded and self.vector_cache:
                    logger.info(f"检测到 {len(self.vector_cache)} 个向量缓存，重建索引")
                    await self._rebuild_index()

            # 加载统计信息
            stats_file = self.storage_path / "storage_stats.json"
            if stats_file.exists():
                with open(stats_file, encoding="utf-8") as f:
                    self.storage_stats = orjson.loads(f.read())

            # 更新向量计数
            self.storage_stats["total_vectors"] = len(self.memory_id_to_index)

            logger.info(f"✅ 向量存储加载完成，{self.storage_stats['total_vectors']} 个向量")

        except Exception as e:
            logger.error(f"❌ 加载向量存储失败: {e}")

    async def _rebuild_index(self):
        """重建向量索引"""
        try:
            logger.info(f"正在重建向量索引...向量数量: {len(self.vector_cache)}")

            # 重新初始化索引
            self._initialize_index()

            # 清空映射关系
            self.memory_id_to_index.clear()
            self.index_to_memory_id.clear()

            if not self.vector_cache:
                logger.warning("没有向量缓存数据，跳过重建")
                return

            # 准备向量数据
            memory_ids = []
            vectors = []

            for memory_id, embedding in self.vector_cache.items():
                if embedding and len(embedding) == self.config.dimension:
                    memory_ids.append(memory_id)
                    vectors.append(self._normalize_vector(embedding))
                else:
                    logger.debug(f"跳过无效向量: {memory_id}, 维度: {len(embedding) if embedding else 0}")

            if not vectors:
                logger.warning("没有有效的向量数据")
                return

            logger.info(f"准备重建 {len(vectors)} 个向量到索引")

            # 批量添加向量到FAISS索引
            if hasattr(self.vector_index, "add"):
                # FAISS索引
                vector_array = np.array(vectors, dtype="float32")

                # 特殊处理IVF索引
                if self.config.index_type == "ivf" and hasattr(self.vector_index, "train"):
                    logger.info("训练IVF索引...")
                    self.vector_index.train(vector_array)

                # 添加向量
                self.vector_index.add(vector_array)

                # 重建映射关系
                for i, memory_id in enumerate(memory_ids):
                    self.memory_id_to_index[memory_id] = i
                    self.index_to_memory_id[i] = memory_id

            else:
                # 简单索引
                for i, (memory_id, vector) in enumerate(zip(memory_ids, vectors, strict=False)):
                    index_id = self.vector_index.add_vector(vector)
                    self.memory_id_to_index[memory_id] = index_id
                    self.index_to_memory_id[index_id] = memory_id

            # 更新统计
            self.storage_stats["total_vectors"] = len(self.memory_id_to_index)

            final_count = getattr(self.vector_index, "ntotal", len(self.memory_id_to_index))
            logger.info(f"✅ 向量索引重建完成，索引中向量数: {final_count}")

        except Exception as e:
            logger.error(f"❌ 重建向量索引失败: {e}", exc_info=True)

    async def optimize_storage(self):
        """优化存储"""
        try:
            logger.info("开始向量存储优化...")

            # 清理无效引用
            self._cleanup_invalid_references()

            # 重新构建索引（如果碎片化严重）
            if self.storage_stats["total_vectors"] > 1000:
                await self._rebuild_index()

            # 更新缓存命中率
            if self.storage_stats["total_searches"] > 0:
                self.storage_stats["cache_hit_rate"] = (
                    self.storage_stats["cache_hits"] / self.storage_stats["total_searches"]
                )

            logger.info("✅ 向量存储优化完成")

        except Exception as e:
            logger.error(f"❌ 向量存储优化失败: {e}")

    def _cleanup_invalid_references(self):
        """清理无效引用"""
        with self._lock:
            # 清理无效的memory_id到index的映射
            valid_memory_ids = set(self.memory_cache.keys())
            invalid_memory_ids = set(self.memory_id_to_index.keys()) - valid_memory_ids

            for memory_id in invalid_memory_ids:
                index = self.memory_id_to_index[memory_id]
                del self.memory_id_to_index[memory_id]
                if index in self.index_to_memory_id:
                    del self.index_to_memory_id[index]

            if invalid_memory_ids:
                logger.info(f"清理了 {len(invalid_memory_ids)} 个无效引用")

    def get_storage_stats(self) -> dict[str, Any]:
        """获取存储统计信息"""
        stats = self.storage_stats.copy()
        if stats["total_searches"] > 0:
            stats["cache_hit_rate"] = stats["cache_hits"] / stats["total_searches"]
        else:
            stats["cache_hit_rate"] = 0.0
        return stats


class SimpleVectorIndex:
    """简单的向量索引实现（当FAISS不可用时的替代方案）"""

    def __init__(self, dimension: int):
        self.dimension = dimension
        self.vectors: list[list[float]] = []
        self.vector_ids: list[int] = []
        self.next_id = 0

    def add_vector(self, vector: list[float]) -> int:
        """添加向量"""
        if len(vector) != self.dimension:
            raise ValueError(f"向量维度不匹配，期望 {self.dimension}，实际 {len(vector)}")

        vector_id = self.next_id
        self.vectors.append(vector.copy())
        self.vector_ids.append(vector_id)
        self.next_id += 1

        return vector_id

    def search(self, query_vector: list[float], limit: int) -> list[tuple[int, float]]:
        """搜索相似向量"""
        if len(query_vector) != self.dimension:
            raise ValueError(f"查询向量维度不匹配，期望 {self.dimension}，实际 {len(query_vector)}")

        results = []

        for i, vector in enumerate(self.vectors):
            similarity = self._calculate_cosine_similarity(query_vector, vector)
            results.append((self.vector_ids[i], similarity))

        # 按相似度排序
        results.sort(key=lambda x: x[1], reverse=True)

        return results[:limit]

    def _calculate_cosine_similarity(self, v1: list[float], v2: list[float]) -> float:
        """计算余弦相似度"""
        try:
            dot_product = sum(x * y for x, y in zip(v1, v2, strict=False))
            norm1 = sum(x * x for x in v1) ** 0.5
            norm2 = sum(x * x for x in v2) ** 0.5

            if norm1 == 0 or norm2 == 0:
                return 0.0

            return dot_product / (norm1 * norm2)

        except Exception:
            return 0.0

    @property
    def ntotal(self) -> int:
        """向量总数"""
        return len(self.vectors)
