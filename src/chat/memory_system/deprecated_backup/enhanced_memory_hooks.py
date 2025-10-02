"""
增强记忆系统钩子
用于在消息处理过程中自动构建和检索记忆
"""

from datetime import datetime
from typing import Any

from src.chat.memory_system.enhanced_memory_manager import enhanced_memory_manager

from src.common.logger import get_logger
from src.config.config import global_config

logger = get_logger(__name__)


class EnhancedMemoryHooks:
    """增强记忆系统钩子 - 自动处理消息的记忆构建和检索"""

    def __init__(self):
        self.enabled = global_config.memory.enable_memory and global_config.memory.enable_enhanced_memory
        self.processed_messages = set()  # 避免重复处理

    async def process_message_for_memory(
        self,
        message_content: str,
        user_id: str,
        chat_id: str,
        message_id: str,
        context: dict[str, Any] | None = None,
    ) -> bool:
        """
        处理消息并构建记忆

        Args:
            message_content: 消息内容
            user_id: 用户ID
            chat_id: 聊天ID
            message_id: 消息ID
            context: 上下文信息

        Returns:
            bool: 是否成功处理
        """
        if not self.enabled:
            return False

        if message_id in self.processed_messages:
            return False

        try:
            # 确保增强记忆管理器已初始化
            if not enhanced_memory_manager.is_initialized:
                await enhanced_memory_manager.initialize()

            # 注入机器人基础人设，帮助记忆构建时避免记录自身信息
            bot_config = getattr(global_config, "bot", None)
            personality_config = getattr(global_config, "personality", None)
            bot_context = {}
            if bot_config is not None:
                bot_context["bot_name"] = getattr(bot_config, "nickname", None)
                bot_context["bot_aliases"] = list(getattr(bot_config, "alias_names", []) or [])
                bot_context["bot_account"] = getattr(bot_config, "qq_account", None)

            if personality_config is not None:
                bot_context["bot_identity"] = getattr(personality_config, "identity", None)
                bot_context["bot_personality"] = getattr(personality_config, "personality_core", None)
                bot_context["bot_personality_side"] = getattr(personality_config, "personality_side", None)

            # 构建上下文
            memory_context = {
                "chat_id": chat_id,
                "message_id": message_id,
                "timestamp": datetime.now().timestamp(),
                "message_type": "user_message",
                **bot_context,
                **(context or {}),
            }

            # 处理对话并构建记忆
            memory_chunks = await enhanced_memory_manager.process_conversation(
                conversation_text=message_content,
                context=memory_context,
                user_id=user_id,
                timestamp=memory_context["timestamp"],
            )

            # 标记消息已处理
            self.processed_messages.add(message_id)

            # 限制处理历史大小
            if len(self.processed_messages) > 1000:
                # 移除最旧的500个记录
                self.processed_messages = set(list(self.processed_messages)[-500:])

            logger.debug(f"为消息 {message_id} 构建了 {len(memory_chunks)} 条记忆")
            return len(memory_chunks) > 0

        except Exception as e:
            logger.error(f"处理消息记忆失败: {e}")
            return False

    async def get_memory_for_response(
        self,
        query_text: str,
        user_id: str,
        chat_id: str,
        limit: int = 5,
        extra_context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        为回复获取相关记忆

        Args:
            query_text: 查询文本
            user_id: 用户ID
            chat_id: 聊天ID
            limit: 返回记忆数量限制

        Returns:
            List[Dict]: 相关记忆列表
        """
        if not self.enabled:
            return []

        try:
            # 确保增强记忆管理器已初始化
            if not enhanced_memory_manager.is_initialized:
                await enhanced_memory_manager.initialize()

            # 构建查询上下文
            context = {
                "chat_id": chat_id,
                "query_intent": "response_generation",
                "expected_memory_types": ["personal_fact", "event", "preference", "opinion"],
            }

            if extra_context:
                context.update(extra_context)

            # 获取相关记忆
            enhanced_results = await enhanced_memory_manager.get_enhanced_memory_context(
                query_text=query_text, user_id=user_id, context=context, limit=limit
            )

            # 转换为字典格式
            results = []
            for result in enhanced_results:
                memory_dict = {
                    "content": result.content,
                    "type": result.memory_type,
                    "confidence": result.confidence,
                    "importance": result.importance,
                    "timestamp": result.timestamp,
                    "source": result.source,
                    "relevance": result.relevance_score,
                    "structure": result.structure,
                }
                results.append(memory_dict)

            logger.debug(f"为回复查询到 {len(results)} 条相关记忆")
            return results

        except Exception as e:
            logger.error(f"获取回复记忆失败: {e}")
            return []

    async def cleanup_old_memories(self):
        """清理旧记忆"""
        try:
            if enhanced_memory_manager.is_initialized:
                # 调用增强记忆系统的维护功能
                await enhanced_memory_manager.enhanced_system.maintenance()
                logger.debug("增强记忆系统维护完成")
        except Exception as e:
            logger.error(f"清理旧记忆失败: {e}")

    def clear_processed_cache(self):
        """清除已处理消息的缓存"""
        self.processed_messages.clear()
        logger.debug("已清除消息处理缓存")

    def enable(self):
        """启用记忆钩子"""
        self.enabled = True
        logger.info("增强记忆钩子已启用")

    def disable(self):
        """禁用记忆钩子"""
        self.enabled = False
        logger.info("增强记忆钩子已禁用")


# 创建全局实例
enhanced_memory_hooks = EnhancedMemoryHooks()
