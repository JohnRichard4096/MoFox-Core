"""
统一记忆管理器 (Unified Memory Manager)

整合三层记忆系统：
- 感知记忆层
- 短期记忆层
- 长期记忆层

提供统一的接口供外部调用
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from src.common.logger import get_logger
from src.memory_graph.manager import MemoryManager
from src.memory_graph.three_tier.long_term_manager import LongTermMemoryManager
from src.memory_graph.three_tier.models import JudgeDecision, MemoryBlock, ShortTermMemory
from src.memory_graph.three_tier.perceptual_manager import PerceptualMemoryManager
from src.memory_graph.three_tier.short_term_manager import ShortTermMemoryManager

logger = get_logger(__name__)


class UnifiedMemoryManager:
    """
    统一记忆管理器

    整合三层记忆系统，提供统一接口
    """

    def __init__(
        self,
        data_dir: Path | None = None,
        # 感知记忆配置
        perceptual_max_blocks: int = 50,
        perceptual_block_size: int = 5,
        perceptual_activation_threshold: int = 3,
        perceptual_recall_top_k: int = 5,
        perceptual_recall_threshold: float = 0.55,
        # 短期记忆配置
        short_term_max_memories: int = 30,
        short_term_transfer_threshold: float = 0.6,
        # 长期记忆配置
        long_term_batch_size: int = 10,
        long_term_search_top_k: int = 5,
        long_term_decay_factor: float = 0.95,
        # 智能检索配置
        judge_confidence_threshold: float = 0.7,
    ):
        """
        初始化统一记忆管理器

        Args:
            data_dir: 数据存储目录
            perceptual_max_blocks: 感知记忆堆最大容量
            perceptual_block_size: 每个记忆块的消息数量
            perceptual_activation_threshold: 激活阈值（召回次数）
            perceptual_recall_top_k: 召回时返回的最大块数
            perceptual_recall_threshold: 召回的相似度阈值
            short_term_max_memories: 短期记忆最大数量
            short_term_transfer_threshold: 转移到长期记忆的重要性阈值
            long_term_batch_size: 批量处理的短期记忆数量
            long_term_search_top_k: 检索相似记忆的数量
            long_term_decay_factor: 长期记忆的衰减因子
            judge_confidence_threshold: 裁判模型的置信度阈值
        """
        self.data_dir = data_dir or Path("data/memory_graph/three_tier")
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 配置参数
        self.judge_confidence_threshold = judge_confidence_threshold

        # 三层管理器
        self.perceptual_manager: PerceptualMemoryManager | None = None
        self.short_term_manager: ShortTermMemoryManager | None = None
        self.long_term_manager: LongTermMemoryManager | None = None

        # 底层 MemoryManager（长期记忆）
        self.memory_manager: MemoryManager | None = None

        # 配置参数存储（用于初始化）
        self._config = {
            "perceptual": {
                "max_blocks": perceptual_max_blocks,
                "block_size": perceptual_block_size,
                "activation_threshold": perceptual_activation_threshold,
                "recall_top_k": perceptual_recall_top_k,
                "recall_similarity_threshold": perceptual_recall_threshold,
            },
            "short_term": {
                "max_memories": short_term_max_memories,
                "transfer_importance_threshold": short_term_transfer_threshold,
            },
            "long_term": {
                "batch_size": long_term_batch_size,
                "search_top_k": long_term_search_top_k,
                "long_term_decay_factor": long_term_decay_factor,
            },
        }

        # 状态
        self._initialized = False
        self._auto_transfer_task: asyncio.Task | None = None

        logger.info("统一记忆管理器已创建")

    async def initialize(self) -> None:
        """初始化统一记忆管理器"""
        if self._initialized:
            logger.warning("统一记忆管理器已经初始化")
            return

        try:
            logger.info("开始初始化统一记忆管理器...")

            # 初始化底层 MemoryManager（长期记忆）
            self.memory_manager = MemoryManager(data_dir=self.data_dir.parent)
            await self.memory_manager.initialize()

            # 初始化感知记忆层
            self.perceptual_manager = PerceptualMemoryManager(
                data_dir=self.data_dir,
                **self._config["perceptual"],
            )
            await self.perceptual_manager.initialize()

            # 初始化短期记忆层
            self.short_term_manager = ShortTermMemoryManager(
                data_dir=self.data_dir,
                **self._config["short_term"],
            )
            await self.short_term_manager.initialize()

            # 初始化长期记忆层
            self.long_term_manager = LongTermMemoryManager(
                memory_manager=self.memory_manager,
                **self._config["long_term"],
            )
            await self.long_term_manager.initialize()

            self._initialized = True
            logger.info("✅ 统一记忆管理器初始化完成")

            # 启动自动转移任务
            self._start_auto_transfer_task()

        except Exception as e:
            logger.error(f"统一记忆管理器初始化失败: {e}", exc_info=True)
            raise

    async def add_message(self, message: dict[str, Any]) -> MemoryBlock | None:
        """
        添加消息到感知记忆层

        Args:
            message: 消息字典

        Returns:
            如果创建了新块，返回 MemoryBlock
        """
        if not self._initialized:
            await self.initialize()

        new_block = await self.perceptual_manager.add_message(message)

        # 注意：感知→短期的转移由召回触发，不是由添加消息触发
        # 转移逻辑在 search_memories 中处理

        return new_block

    # 已移除 _process_activated_blocks 方法
    # 转移逻辑现在在 search_memories 中处理：
    # 当召回某个记忆块时，如果其 recall_count >= activation_threshold，
    # 立即将该块转移到短期记忆

    async def search_memories(
        self, query_text: str, use_judge: bool = True
    ) -> dict[str, Any]:
        """
        智能检索记忆

        流程：
        1. 优先检索感知记忆和短期记忆
        2. 使用裁判模型评估是否充足
        3. 如果不充足，生成补充 query 并检索长期记忆

        Args:
            query_text: 查询文本
            use_judge: 是否使用裁判模型

        Returns:
            检索结果字典，包含：
            - perceptual_blocks: 感知记忆块列表
            - short_term_memories: 短期记忆列表
            - long_term_memories: 长期记忆列表
            - judge_decision: 裁判决策（如果使用）
        """
        if not self._initialized:
            await self.initialize()

        try:
            result = {
                "perceptual_blocks": [],
                "short_term_memories": [],
                "long_term_memories": [],
                "judge_decision": None,
            }

            # 步骤1: 检索感知记忆和短期记忆
            perceptual_blocks = await self.perceptual_manager.recall_blocks(query_text)
            short_term_memories = await self.short_term_manager.search_memories(query_text)

            # 步骤1.5: 检查并处理需要转移的记忆块
            # 当某个块的召回次数达到阈值时，立即转移到短期记忆
            blocks_to_transfer = [
                block for block in perceptual_blocks
                if block.metadata.get("needs_transfer", False)
            ]
            
            if blocks_to_transfer:
                logger.info(f"检测到 {len(blocks_to_transfer)} 个记忆块需要转移到短期记忆")
                for block in blocks_to_transfer:
                    # 转换为短期记忆
                    stm = await self.short_term_manager.add_from_block(block)
                    if stm:
                        # 从感知记忆中移除
                        await self.perceptual_manager.remove_block(block.id)
                        logger.info(f"✅ 记忆块 {block.id} 已转为短期记忆 {stm.id}")
                        # 将新创建的短期记忆加入结果
                        short_term_memories.append(stm)

            result["perceptual_blocks"] = perceptual_blocks
            result["short_term_memories"] = short_term_memories

            logger.info(
                f"初步检索: 感知记忆 {len(perceptual_blocks)} 块, "
                f"短期记忆 {len(short_term_memories)} 条"
            )

            # 步骤2: 裁判模型评估
            if use_judge:
                judge_decision = await self._judge_retrieval_sufficiency(
                    query_text, perceptual_blocks, short_term_memories
                )
                result["judge_decision"] = judge_decision

                # 步骤3: 如果不充足，检索长期记忆
                if not judge_decision.is_sufficient:
                    logger.info("裁判判定记忆不充足，启动长期记忆检索")

                    # 使用额外的 query 检索
                    long_term_memories = []
                    queries = [query_text] + judge_decision.additional_queries

                    for q in queries:
                        memories = await self.memory_manager.search_memories(
                            query=q,
                            top_k=5,
                            use_multi_query=False,
                        )
                        long_term_memories.extend(memories)

                    # 去重
                    seen_ids = set()
                    unique_memories = []
                    for mem in long_term_memories:
                        if mem.id not in seen_ids:
                            unique_memories.append(mem)
                            seen_ids.add(mem.id)

                    result["long_term_memories"] = unique_memories
                    logger.info(f"长期记忆检索: {len(unique_memories)} 条")
            else:
                # 不使用裁判，直接检索长期记忆
                long_term_memories = await self.memory_manager.search_memories(
                    query=query_text,
                    top_k=5,
                    use_multi_query=False,
                )
                result["long_term_memories"] = long_term_memories

            return result

        except Exception as e:
            logger.error(f"智能检索失败: {e}", exc_info=True)
            return {
                "perceptual_blocks": [],
                "short_term_memories": [],
                "long_term_memories": [],
                "error": str(e),
            }

    async def _judge_retrieval_sufficiency(
        self,
        query: str,
        perceptual_blocks: list[MemoryBlock],
        short_term_memories: list[ShortTermMemory],
    ) -> JudgeDecision:
        """
        使用裁判模型评估检索结果是否充足

        Args:
            query: 原始查询
            perceptual_blocks: 感知记忆块
            short_term_memories: 短期记忆

        Returns:
            裁判决策
        """
        try:
            from src.config.config import model_config
            from src.llm_models.utils_model import LLMRequest

            # 构建提示词
            perceptual_desc = "\n\n".join(
                [f"记忆块{i+1}:\n{block.combined_text}" for i, block in enumerate(perceptual_blocks)]
            )

            short_term_desc = "\n\n".join(
                [f"记忆{i+1}:\n{mem.content}" for i, mem in enumerate(short_term_memories)]
            )

            prompt = f"""你是一个记忆检索评估专家。请判断检索到的记忆是否足以回答用户的问题。

**用户查询：**
{query}

**检索到的感知记忆块：**
{perceptual_desc or '（无）'}

**检索到的短期记忆：**
{short_term_desc or '（无）'}

**任务要求：**
1. 判断这些记忆是否足以回答用户的问题
2. 如果不充足，分析缺少哪些方面的信息
3. 生成额外需要检索的 query（用于在长期记忆中检索）

**输出格式（JSON）：**
```json
{{
  "is_sufficient": true/false,
  "confidence": 0.85,
  "reasoning": "判断理由",
  "missing_aspects": ["缺失的信息1", "缺失的信息2"],
  "additional_queries": ["补充query1", "补充query2"]
}}
```

请输出JSON："""

            # 调用 LLM
            llm = LLMRequest(
                model_set=model_config.model_task_config.utils_small,
                request_type="unified_memory.judge",
            )

            response, _ = await llm.generate_response_async(
                prompt,
                temperature=0.2,
                max_tokens=800,
            )

            # 解析响应
            import json
            import re

            json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = response.strip()

            data = json.loads(json_str)

            decision = JudgeDecision(
                is_sufficient=data.get("is_sufficient", False),
                confidence=data.get("confidence", 0.5),
                reasoning=data.get("reasoning", ""),
                additional_queries=data.get("additional_queries", []),
                missing_aspects=data.get("missing_aspects", []),
            )

            logger.info(f"裁判决策: {decision}")
            return decision

        except Exception as e:
            logger.error(f"裁判模型评估失败: {e}", exc_info=True)
            # 默认判定为不充足，需要检索长期记忆
            return JudgeDecision(
                is_sufficient=False,
                confidence=0.3,
                reasoning=f"裁判模型失败: {e}",
                additional_queries=[query],
            )

    def _start_auto_transfer_task(self) -> None:
        """启动自动转移任务"""
        if self._auto_transfer_task and not self._auto_transfer_task.done():
            logger.warning("自动转移任务已在运行")
            return

        self._auto_transfer_task = asyncio.create_task(self._auto_transfer_loop())
        logger.info("自动转移任务已启动")

    async def _auto_transfer_loop(self) -> None:
        """自动转移循环"""
        while True:
            try:
                # 每 10 分钟检查一次
                await asyncio.sleep(600)

                # 检查短期记忆是否达到上限
                if len(self.short_term_manager.memories) >= self.short_term_manager.max_memories:
                    logger.info("短期记忆已达上限，开始转移到长期记忆")

                    # 获取待转移的记忆
                    memories_to_transfer = self.short_term_manager.get_memories_for_transfer()

                    if memories_to_transfer:
                        # 执行转移
                        result = await self.long_term_manager.transfer_from_short_term(
                            memories_to_transfer
                        )

                        # 清除已转移的记忆
                        if result.get("transferred_memory_ids"):
                            await self.short_term_manager.clear_transferred_memories(
                                result["transferred_memory_ids"]
                            )

                        logger.info(f"自动转移完成: {result}")

            except asyncio.CancelledError:
                logger.info("自动转移任务已取消")
                break
            except Exception as e:
                logger.error(f"自动转移任务错误: {e}", exc_info=True)
                # 继续运行

    async def manual_transfer(self) -> dict[str, Any]:
        """
        手动触发短期记忆到长期记忆的转移

        Returns:
            转移结果
        """
        if not self._initialized:
            await self.initialize()

        try:
            memories_to_transfer = self.short_term_manager.get_memories_for_transfer()

            if not memories_to_transfer:
                logger.info("没有需要转移的短期记忆")
                return {"message": "没有需要转移的记忆", "transferred_count": 0}

            # 执行转移
            result = await self.long_term_manager.transfer_from_short_term(memories_to_transfer)

            # 清除已转移的记忆
            if result.get("transferred_memory_ids"):
                await self.short_term_manager.clear_transferred_memories(
                    result["transferred_memory_ids"]
                )

            logger.info(f"手动转移完成: {result}")
            return result

        except Exception as e:
            logger.error(f"手动转移失败: {e}", exc_info=True)
            return {"error": str(e), "transferred_count": 0}

    def get_statistics(self) -> dict[str, Any]:
        """获取三层记忆系统的统计信息"""
        if not self._initialized:
            return {}

        return {
            "perceptual": self.perceptual_manager.get_statistics(),
            "short_term": self.short_term_manager.get_statistics(),
            "long_term": self.long_term_manager.get_statistics(),
            "total_system_memories": (
                self.perceptual_manager.get_statistics().get("total_messages", 0)
                + self.short_term_manager.get_statistics().get("total_memories", 0)
                + self.long_term_manager.get_statistics().get("total_memories", 0)
            ),
        }

    async def shutdown(self) -> None:
        """关闭统一记忆管理器"""
        if not self._initialized:
            return

        try:
            logger.info("正在关闭统一记忆管理器...")

            # 取消自动转移任务
            if self._auto_transfer_task and not self._auto_transfer_task.done():
                self._auto_transfer_task.cancel()
                try:
                    await self._auto_transfer_task
                except asyncio.CancelledError:
                    pass

            # 关闭各层管理器
            if self.perceptual_manager:
                await self.perceptual_manager.shutdown()

            if self.short_term_manager:
                await self.short_term_manager.shutdown()

            if self.long_term_manager:
                await self.long_term_manager.shutdown()

            if self.memory_manager:
                await self.memory_manager.shutdown()

            self._initialized = False
            logger.info("✅ 统一记忆管理器已关闭")

        except Exception as e:
            logger.error(f"关闭统一记忆管理器失败: {e}", exc_info=True)
