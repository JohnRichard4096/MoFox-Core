"""
记忆系统集成钩子
提供与现有MoFox Bot系统的无缝集成点
"""

import time
from dataclasses import dataclass
from typing import Any

from src.chat.memory_system.enhanced_memory_adapter import (
    get_memory_context_for_prompt,
    process_conversation_with_enhanced_memory,
    retrieve_memories_with_enhanced_system,
)

from src.common.logger import get_logger

logger = get_logger(__name__)


@dataclass
class HookResult:
    """钩子执行结果"""

    success: bool
    data: Any = None
    error: str | None = None
    processing_time: float = 0.0


class MemoryIntegrationHooks:
    """记忆系统集成钩子"""

    def __init__(self):
        self.hooks_registered = False
        self.hook_stats = {
            "message_processing_hooks": 0,
            "memory_retrieval_hooks": 0,
            "prompt_enhancement_hooks": 0,
            "total_hook_executions": 0,
            "average_hook_time": 0.0,
        }

    async def register_hooks(self):
        """注册所有集成钩子"""
        if self.hooks_registered:
            return

        try:
            logger.info("🔗 注册记忆系统集成钩子...")

            # 注册消息处理钩子
            await self._register_message_processing_hooks()

            # 注册记忆检索钩子
            await self._register_memory_retrieval_hooks()

            # 注册提示词增强钩子
            await self._register_prompt_enhancement_hooks()

            # 注册系统维护钩子
            await self._register_maintenance_hooks()

            self.hooks_registered = True
            logger.info("✅ 记忆系统集成钩子注册完成")

        except Exception as e:
            logger.error(f"❌ 注册记忆系统集成钩子失败: {e}", exc_info=True)

    async def _register_message_processing_hooks(self):
        """注册消息处理钩子"""
        try:
            # 钩子1: 在消息处理后创建记忆
            await self._register_post_message_hook()

            # 钩子2: 在聊天流保存时处理记忆
            await self._register_chat_stream_hook()

            logger.debug("消息处理钩子注册完成")

        except Exception as e:
            logger.error(f"注册消息处理钩子失败: {e}")

    async def _register_memory_retrieval_hooks(self):
        """注册记忆检索钩子"""
        try:
            # 钩子1: 在生成回复前检索相关记忆
            await self._register_pre_response_hook()

            # 钩子2: 在知识库查询前增强上下文
            await self._register_knowledge_query_hook()

            logger.debug("记忆检索钩子注册完成")

        except Exception as e:
            logger.error(f"注册记忆检索钩子失败: {e}")

    async def _register_prompt_enhancement_hooks(self):
        """注册提示词增强钩子"""
        try:
            # 钩子1: 增强提示词构建
            await self._register_prompt_building_hook()

            logger.debug("提示词增强钩子注册完成")

        except Exception as e:
            logger.error(f"注册提示词增强钩子失败: {e}")

    async def _register_maintenance_hooks(self):
        """注册系统维护钩子"""
        try:
            # 钩子1: 系统维护时的记忆系统维护
            await self._register_system_maintenance_hook()

            logger.debug("系统维护钩子注册完成")

        except Exception as e:
            logger.error(f"注册系统维护钩子失败: {e}")

    async def _register_post_message_hook(self):
        """注册消息后处理钩子"""
        try:
            # 这里需要根据实际的系统架构来注册钩子
            # 以下是一个示例实现，需要根据实际的插件系统或事件系统来调整

            # 尝试注册到事件系统
            try:
                from src.plugin_system.base.component_types import EventType
                from src.plugin_system.core.event_manager import event_manager

                # 注册消息后处理事件
                event_manager.subscribe(EventType.MESSAGE_PROCESSED, self._on_message_processed_handler)
                logger.debug("已注册到事件系统的消息处理钩子")

            except ImportError:
                logger.debug("事件系统不可用，跳过事件钩子注册")

            # 尝试注册到消息管理器
            try:
                from src.chat.message_manager import message_manager

                # 如果消息管理器支持钩子注册
                if hasattr(message_manager, "register_post_process_hook"):
                    message_manager.register_post_process_hook(self._on_message_processed_hook)
                    logger.debug("已注册到消息管理器的处理钩子")

            except ImportError:
                logger.debug("消息管理器不可用，跳过消息管理器钩子注册")

        except Exception as e:
            logger.error(f"注册消息后处理钩子失败: {e}")

    async def _register_chat_stream_hook(self):
        """注册聊天流钩子"""
        try:
            # 尝试注册到聊天流管理器
            try:
                from src.chat.message_receive.chat_stream import get_chat_manager

                chat_manager = get_chat_manager()
                if hasattr(chat_manager, "register_save_hook"):
                    chat_manager.register_save_hook(self._on_chat_stream_save_hook)
                    logger.debug("已注册到聊天流管理器的保存钩子")

            except ImportError:
                logger.debug("聊天流管理器不可用，跳过聊天流钩子注册")

        except Exception as e:
            logger.error(f"注册聊天流钩子失败: {e}")

    async def _register_pre_response_hook(self):
        """注册回复前钩子"""
        try:
            # 尝试注册到回复生成器
            try:
                from src.chat.replyer.default_generator import default_generator

                if hasattr(default_generator, "register_pre_generation_hook"):
                    default_generator.register_pre_generation_hook(self._on_pre_response_hook)
                    logger.debug("已注册到回复生成器的前置钩子")

            except ImportError:
                logger.debug("回复生成器不可用，跳过回复前钩子注册")

        except Exception as e:
            logger.error(f"注册回复前钩子失败: {e}")

    async def _register_knowledge_query_hook(self):
        """注册知识库查询钩子"""
        try:
            # 尝试注册到知识库系统
            try:
                from src.chat.knowledge.knowledge_lib import knowledge_manager

                if hasattr(knowledge_manager, "register_query_enhancer"):
                    knowledge_manager.register_query_enhancer(self._on_knowledge_query_hook)
                    logger.debug("已注册到知识库的查询增强钩子")

            except ImportError:
                logger.debug("知识库系统不可用，跳过知识库钩子注册")

        except Exception as e:
            logger.error(f"注册知识库查询钩子失败: {e}")

    async def _register_prompt_building_hook(self):
        """注册提示词构建钩子"""
        try:
            # 尝试注册到提示词系统
            try:
                from src.chat.utils.prompt import prompt_manager

                if hasattr(prompt_manager, "register_enhancer"):
                    prompt_manager.register_enhancer(self._on_prompt_building_hook)
                    logger.debug("已注册到提示词管理器的增强钩子")

            except ImportError:
                logger.debug("提示词系统不可用，跳过提示词钩子注册")

        except Exception as e:
            logger.error(f"注册提示词构建钩子失败: {e}")

    async def _register_system_maintenance_hook(self):
        """注册系统维护钩子"""
        try:
            # 尝试注册到系统维护器
            try:
                from src.manager.async_task_manager import async_task_manager

                # 注册定期维护任务
                async_task_manager.add_task(MemoryMaintenanceTask())
                logger.debug("已注册到系统维护器的定期任务")

            except ImportError:
                logger.debug("异步任务管理器不可用，跳过系统维护钩子注册")

        except Exception as e:
            logger.error(f"注册系统维护钩子失败: {e}")

    # 钩子处理器方法

    async def _on_message_processed_handler(self, event_data: dict[str, Any]) -> HookResult:
        """事件系统的消息处理处理器"""
        return await self._on_message_processed_hook(event_data)

    async def _on_message_processed_hook(self, message_data: dict[str, Any]) -> HookResult:
        """消息后处理钩子"""
        start_time = time.time()

        try:
            self.hook_stats["message_processing_hooks"] += 1

            # 提取必要的信息
            message_info = message_data.get("message_info", {})
            user_info = message_info.get("user_info", {})
            conversation_text = message_data.get("processed_plain_text", "")

            if not conversation_text:
                return HookResult(success=True, data="No conversation text")

            user_id = str(user_info.get("user_id", "unknown"))
            context = {
                "chat_id": message_data.get("chat_id"),
                "message_type": message_data.get("message_type", "normal"),
                "platform": message_info.get("platform", "unknown"),
                "interest_value": message_data.get("interest_value", 0.0),
                "keywords": message_data.get("key_words", []),
                "timestamp": message_data.get("time", time.time()),
            }

            # 使用增强记忆系统处理对话
            memory_context = dict(context)
            memory_context["conversation_text"] = conversation_text
            memory_context["user_id"] = user_id

            result = await process_conversation_with_enhanced_memory(memory_context)

            processing_time = time.time() - start_time
            self._update_hook_stats(processing_time)

            if result["success"]:
                logger.debug(f"消息处理钩子执行成功，创建 {len(result.get('created_memories', []))} 条记忆")
                return HookResult(success=True, data=result, processing_time=processing_time)
            else:
                logger.warning(f"消息处理钩子执行失败: {result.get('error')}")
                return HookResult(success=False, error=result.get("error"), processing_time=processing_time)

        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"消息处理钩子执行异常: {e}", exc_info=True)
            return HookResult(success=False, error=str(e), processing_time=processing_time)

    async def _on_chat_stream_save_hook(self, chat_stream_data: dict[str, Any]) -> HookResult:
        """聊天流保存钩子"""
        start_time = time.time()

        try:
            self.hook_stats["message_processing_hooks"] += 1

            # 从聊天流数据中提取对话信息
            stream_context = chat_stream_data.get("stream_context", {})
            user_id = stream_context.get("user_id", "unknown")
            messages = stream_context.get("messages", [])

            if not messages:
                return HookResult(success=True, data="No messages to process")

            # 构建对话文本
            conversation_parts = []
            for msg in messages[-10:]:  # 只处理最近10条消息
                text = msg.get("processed_plain_text", "")
                if text:
                    conversation_parts.append(f"{msg.get('user_nickname', 'User')}: {text}")

            conversation_text = "\n".join(conversation_parts)
            if not conversation_text:
                return HookResult(success=True, data="No conversation text")

            context = {
                "chat_id": chat_stream_data.get("chat_id"),
                "stream_id": chat_stream_data.get("stream_id"),
                "platform": chat_stream_data.get("platform", "unknown"),
                "message_count": len(messages),
                "timestamp": time.time(),
            }

            # 使用增强记忆系统处理对话
            memory_context = dict(context)
            memory_context["conversation_text"] = conversation_text
            memory_context["user_id"] = user_id

            result = await process_conversation_with_enhanced_memory(memory_context)

            processing_time = time.time() - start_time
            self._update_hook_stats(processing_time)

            if result["success"]:
                logger.debug(f"聊天流保存钩子执行成功，创建 {len(result.get('created_memories', []))} 条记忆")
                return HookResult(success=True, data=result, processing_time=processing_time)
            else:
                logger.warning(f"聊天流保存钩子执行失败: {result.get('error')}")
                return HookResult(success=False, error=result.get("error"), processing_time=processing_time)

        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"聊天流保存钩子执行异常: {e}", exc_info=True)
            return HookResult(success=False, error=str(e), processing_time=processing_time)

    async def _on_pre_response_hook(self, response_data: dict[str, Any]) -> HookResult:
        """回复前钩子"""
        start_time = time.time()

        try:
            self.hook_stats["memory_retrieval_hooks"] += 1

            # 提取查询信息
            query = response_data.get("query", "")
            user_id = response_data.get("user_id", "unknown")
            context = response_data.get("context", {})

            if not query:
                return HookResult(success=True, data="No query provided")

            # 检索相关记忆
            memories = await retrieve_memories_with_enhanced_system(query, user_id, context, limit=5)

            processing_time = time.time() - start_time
            self._update_hook_stats(processing_time)

            # 将记忆添加到响应数据中
            response_data["enhanced_memories"] = memories
            response_data["enhanced_memory_context"] = await get_memory_context_for_prompt(
                query, user_id, context, max_memories=5
            )

            logger.debug(f"回复前钩子执行成功，检索到 {len(memories)} 条记忆")
            return HookResult(success=True, data=memories, processing_time=processing_time)

        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"回复前钩子执行异常: {e}", exc_info=True)
            return HookResult(success=False, error=str(e), processing_time=processing_time)

    async def _on_knowledge_query_hook(self, query_data: dict[str, Any]) -> HookResult:
        """知识库查询钩子"""
        start_time = time.time()

        try:
            self.hook_stats["memory_retrieval_hooks"] += 1

            query = query_data.get("query", "")
            user_id = query_data.get("user_id", "unknown")
            context = query_data.get("context", {})

            if not query:
                return HookResult(success=True, data="No query provided")

            # 获取记忆上下文并增强查询
            memory_context = await get_memory_context_for_prompt(query, user_id, context, max_memories=3)

            processing_time = time.time() - start_time
            self._update_hook_stats(processing_time)

            # 将记忆上下文添加到查询数据中
            query_data["enhanced_memory_context"] = memory_context

            logger.debug("知识库查询钩子执行成功")
            return HookResult(success=True, data=memory_context, processing_time=processing_time)

        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"知识库查询钩子执行异常: {e}", exc_info=True)
            return HookResult(success=False, error=str(e), processing_time=processing_time)

    async def _on_prompt_building_hook(self, prompt_data: dict[str, Any]) -> HookResult:
        """提示词构建钩子"""
        start_time = time.time()

        try:
            self.hook_stats["prompt_enhancement_hooks"] += 1

            query = prompt_data.get("query", "")
            user_id = prompt_data.get("user_id", "unknown")
            context = prompt_data.get("context", {})
            base_prompt = prompt_data.get("base_prompt", "")

            if not query:
                return HookResult(success=True, data="No query provided")

            # 获取记忆上下文
            memory_context = await get_memory_context_for_prompt(query, user_id, context, max_memories=5)

            processing_time = time.time() - start_time
            self._update_hook_stats(processing_time)

            # 构建增强的提示词
            enhanced_prompt = base_prompt
            if memory_context:
                enhanced_prompt += f"\n\n### 相关记忆上下文 ###\n{memory_context}\n"

            # 将增强的提示词添加到数据中
            prompt_data["enhanced_prompt"] = enhanced_prompt
            prompt_data["memory_context"] = memory_context

            logger.debug("提示词构建钩子执行成功")
            return HookResult(success=True, data=enhanced_prompt, processing_time=processing_time)

        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"提示词构建钩子执行异常: {e}", exc_info=True)
            return HookResult(success=False, error=str(e), processing_time=processing_time)

    def _update_hook_stats(self, processing_time: float):
        """更新钩子统计"""
        self.hook_stats["total_hook_executions"] += 1

        total_executions = self.hook_stats["total_hook_executions"]
        if total_executions > 0:
            current_avg = self.hook_stats["average_hook_time"]
            new_avg = (current_avg * (total_executions - 1) + processing_time) / total_executions
            self.hook_stats["average_hook_time"] = new_avg

    def get_hook_stats(self) -> dict[str, Any]:
        """获取钩子统计信息"""
        return self.hook_stats.copy()


class MemoryMaintenanceTask:
    """记忆系统维护任务"""

    def __init__(self):
        self.task_name = "enhanced_memory_maintenance"
        self.interval = 3600  # 1小时执行一次

    async def execute(self):
        """执行维护任务"""
        try:
            logger.info("🔧 执行增强记忆系统维护任务...")

            # 获取适配器实例
            try:
                from src.chat.memory_system.enhanced_memory_adapter import _enhanced_memory_adapter

                if _enhanced_memory_adapter:
                    await _enhanced_memory_adapter.maintenance()
                    logger.info("✅ 增强记忆系统维护任务完成")
                else:
                    logger.debug("增强记忆适配器未初始化，跳过维护")
            except Exception as e:
                logger.error(f"增强记忆系统维护失败: {e}")

        except Exception as e:
            logger.error(f"执行维护任务时发生异常: {e}", exc_info=True)

    def get_interval(self) -> int:
        """获取执行间隔"""
        return self.interval

    def get_task_name(self) -> str:
        """获取任务名称"""
        return self.task_name


# 全局钩子实例
_memory_hooks: MemoryIntegrationHooks | None = None


async def get_memory_integration_hooks() -> MemoryIntegrationHooks:
    """获取全局记忆集成钩子实例"""
    global _memory_hooks

    if _memory_hooks is None:
        _memory_hooks = MemoryIntegrationHooks()
        await _memory_hooks.register_hooks()

    return _memory_hooks


async def initialize_memory_integration_hooks():
    """初始化记忆集成钩子"""
    try:
        logger.info("🚀 初始化记忆集成钩子...")
        hooks = await get_memory_integration_hooks()
        logger.info("✅ 记忆集成钩子初始化完成")
        return hooks
    except Exception as e:
        logger.error(f"❌ 记忆集成钩子初始化失败: {e}", exc_info=True)
        return None
