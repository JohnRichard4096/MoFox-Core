"""
增强记忆系统集成层
现在只管理新的增强记忆系统，旧系统已被完全移除
"""

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.chat.memory_system.enhanced_memory_core import EnhancedMemorySystem

from src.chat.memory_system.memory_chunk import MemoryChunk
from src.common.logger import get_logger
from src.llm_models.utils_model import LLMRequest

logger = get_logger(__name__)


class IntegrationMode(Enum):
    """集成模式"""

    REPLACE = "replace"  # 完全替换现有记忆系统
    ENHANCED_ONLY = "enhanced_only"  # 仅使用增强记忆系统


@dataclass
class IntegrationConfig:
    """集成配置"""

    mode: IntegrationMode = IntegrationMode.ENHANCED_ONLY
    enable_enhanced_memory: bool = True
    memory_value_threshold: float = 0.6
    fusion_threshold: float = 0.85
    max_retrieval_results: int = 10
    enable_learning: bool = True


class MemoryIntegrationLayer:
    """记忆系统集成层 - 现在只管理增强记忆系统"""

    def __init__(self, llm_model: LLMRequest, config: IntegrationConfig | None = None):
        self.llm_model = llm_model
        self.config = config or IntegrationConfig()

        # 只初始化增强记忆系统
        self.enhanced_memory: EnhancedMemorySystem | None = None

        # 集成统计
        self.integration_stats = {
            "total_queries": 0,
            "enhanced_queries": 0,
            "memory_creations": 0,
            "average_response_time": 0.0,
            "success_rate": 0.0,
        }

        # 初始化锁
        self._initialization_lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self):
        """初始化集成层"""
        if self._initialized:
            return

        async with self._initialization_lock:
            if self._initialized:
                return

            logger.info("🚀 开始初始化增强记忆系统集成层...")

            try:
                # 初始化增强记忆系统
                if self.config.enable_enhanced_memory:
                    await self._initialize_enhanced_memory()

                self._initialized = True
                logger.info("✅ 增强记忆系统集成层初始化完成")

            except Exception as e:
                logger.error(f"❌ 集成层初始化失败: {e}", exc_info=True)
                raise

    async def _initialize_enhanced_memory(self):
        """初始化增强记忆系统"""
        try:
            logger.debug("初始化增强记忆系统...")

            # 创建增强记忆系统配置
            from src.chat.memory_system.enhanced_memory_core import MemorySystemConfig

            memory_config = MemorySystemConfig.from_global_config()

            # 使用集成配置覆盖部分值
            memory_config.memory_value_threshold = self.config.memory_value_threshold
            memory_config.fusion_similarity_threshold = self.config.fusion_threshold
            memory_config.final_recall_limit = self.config.max_retrieval_results

            # 创建增强记忆系统
            self.enhanced_memory = EnhancedMemorySystem(config=memory_config)

            # 如果外部提供了LLM模型，注入到系统中
            if self.llm_model is not None:
                self.enhanced_memory.llm_model = self.llm_model

            # 初始化系统
            await self.enhanced_memory.initialize()
            logger.info("✅ 增强记忆系统初始化完成")

        except Exception as e:
            logger.error(f"❌ 增强记忆系统初始化失败: {e}", exc_info=True)
            raise

    async def process_conversation(self, context: dict[str, Any]) -> dict[str, Any]:
        """处理对话记忆，仅使用上下文信息"""
        if not self._initialized or not self.enhanced_memory:
            return {"success": False, "error": "Memory system not available"}

        start_time = time.time()
        self.integration_stats["total_queries"] += 1
        self.integration_stats["enhanced_queries"] += 1

        try:
            payload_context = dict(context or {})
            conversation_text = payload_context.get("conversation_text") or payload_context.get("message_content") or ""
            logger.debug("集成层收到记忆构建请求，文本长度=%d", len(conversation_text))

            # 直接使用增强记忆系统处理
            result = await self.enhanced_memory.process_conversation_memory(payload_context)

            # 更新统计
            processing_time = time.time() - start_time
            self._update_response_stats(processing_time, result.get("success", False))

            if result.get("success"):
                created_count = len(result.get("created_memories", []))
                self.integration_stats["memory_creations"] += created_count
                logger.debug(f"对话处理完成，创建 {created_count} 条记忆")

            return result

        except Exception as e:
            processing_time = time.time() - start_time
            self._update_response_stats(processing_time, False)
            logger.error(f"处理对话记忆失败: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def retrieve_relevant_memories(
        self,
        query: str,
        user_id: str | None = None,
        context: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[MemoryChunk]:
        """检索相关记忆"""
        if not self._initialized or not self.enhanced_memory:
            return []

        try:
            limit = limit or self.config.max_retrieval_results
            memories = await self.enhanced_memory.retrieve_relevant_memories(
                query=query, user_id=None, context=context or {}, limit=limit
            )

            memory_count = len(memories)
            logger.debug(f"检索到 {memory_count} 条相关记忆")
            return memories

        except Exception as e:
            logger.error(f"检索相关记忆失败: {e}", exc_info=True)
            return []

    async def get_system_status(self) -> dict[str, Any]:
        """获取系统状态"""
        if not self._initialized:
            return {"status": "not_initialized"}

        try:
            enhanced_status = {}
            if self.enhanced_memory:
                enhanced_status = await self.enhanced_memory.get_system_status()

            return {
                "status": "initialized",
                "mode": self.config.mode.value,
                "enhanced_memory": enhanced_status,
                "integration_stats": self.integration_stats.copy(),
            }

        except Exception as e:
            logger.error(f"获取系统状态失败: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    def get_integration_stats(self) -> dict[str, Any]:
        """获取集成统计信息"""
        return self.integration_stats.copy()

    def _update_response_stats(self, processing_time: float, success: bool):
        """更新响应统计"""
        total_queries = self.integration_stats["total_queries"]
        if total_queries > 0:
            # 更新平均响应时间
            current_avg = self.integration_stats["average_response_time"]
            new_avg = (current_avg * (total_queries - 1) + processing_time) / total_queries
            self.integration_stats["average_response_time"] = new_avg

            # 更新成功率
            if success:
                current_success_rate = self.integration_stats["success_rate"]
                new_success_rate = (current_success_rate * (total_queries - 1) + 1) / total_queries
                self.integration_stats["success_rate"] = new_success_rate

    async def maintenance(self):
        """执行维护操作"""
        if not self._initialized:
            return

        try:
            logger.info("🔧 执行记忆系统集成层维护...")

            if self.enhanced_memory:
                await self.enhanced_memory.maintenance()

            logger.info("✅ 记忆系统集成层维护完成")

        except Exception as e:
            logger.error(f"❌ 集成层维护失败: {e}", exc_info=True)

    async def shutdown(self):
        """关闭集成层"""
        if not self._initialized:
            return

        try:
            logger.info("🔄 关闭记忆系统集成层...")

            if self.enhanced_memory:
                await self.enhanced_memory.shutdown()

            self._initialized = False
            logger.info("✅ 记忆系统集成层已关闭")

        except Exception as e:
            logger.error(f"❌ 关闭集成层失败: {e}", exc_info=True)
