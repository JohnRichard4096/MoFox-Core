"""
增强记忆系统集成脚本
用于在现有系统中无缝集成增强记忆功能
"""

from typing import Any

from src.chat.memory_system.enhanced_memory_hooks import enhanced_memory_hooks

from src.common.logger import get_logger

logger = get_logger(__name__)


async def process_user_message_memory(
    message_content: str, user_id: str, chat_id: str, message_id: str, context: dict[str, Any] | None = None
) -> bool:
    """
    处理用户消息并构建记忆

    Args:
        message_content: 消息内容
        user_id: 用户ID
        chat_id: 聊天ID
        message_id: 消息ID
        context: 额外的上下文信息

    Returns:
        bool: 是否成功构建记忆
    """
    try:
        success = await enhanced_memory_hooks.process_message_for_memory(
            message_content=message_content, user_id=user_id, chat_id=chat_id, message_id=message_id, context=context
        )

        if success:
            logger.debug(f"成功为消息 {message_id} 构建记忆")

        return success

    except Exception as e:
        logger.error(f"处理用户消息记忆失败: {e}")
        return False


async def get_relevant_memories_for_response(
    query_text: str, user_id: str, chat_id: str, limit: int = 5, extra_context: dict[str, Any] | None = None
) -> dict[str, Any]:
    """
    为回复获取相关记忆

    Args:
        query_text: 查询文本（通常是用户的当前消息）
        user_id: 用户ID
        chat_id: 聊天ID
    limit: 返回记忆数量限制
    extra_context: 额外上下文信息

    Returns:
        Dict: 包含记忆信息的字典
    """
    try:
        memories = await enhanced_memory_hooks.get_memory_for_response(
            query_text=query_text, user_id=user_id, chat_id=chat_id, limit=limit, extra_context=extra_context
        )

        result = {"has_memories": len(memories) > 0, "memories": memories, "memory_count": len(memories)}

        logger.debug(f"为回复获取到 {len(memories)} 条相关记忆")
        return result

    except Exception as e:
        logger.error(f"获取回复记忆失败: {e}")
        return {"has_memories": False, "memories": [], "memory_count": 0}


def format_memories_for_prompt(memories: dict[str, Any]) -> str:
    """
    格式化记忆信息用于Prompt

    Args:
        memories: 记忆信息字典

    Returns:
        str: 格式化后的记忆文本
    """
    if not memories["has_memories"]:
        return ""

    memory_lines = ["以下是相关的记忆信息："]

    for memory in memories["memories"]:
        content = memory["content"]
        memory_type = memory["type"]
        confidence = memory["confidence"]
        importance = memory["importance"]

        # 根据重要性添加不同的标记
        importance_marker = "🔥" if importance >= 3 else "⭐" if importance >= 2 else "📝"
        confidence_marker = "✅" if confidence >= 3 else "⚠️" if confidence >= 2 else "💭"

        memory_line = f"{importance_marker} {content} ({memory_type}, {confidence_marker}置信度)"
        memory_lines.append(memory_line)

    return "\n".join(memory_lines)


async def cleanup_memory_system():
    """清理记忆系统"""
    try:
        await enhanced_memory_hooks.cleanup_old_memories()
        logger.info("记忆系统清理完成")
    except Exception as e:
        logger.error(f"记忆系统清理失败: {e}")


def get_memory_system_status() -> dict[str, Any]:
    """
    获取记忆系统状态

    Returns:
        Dict: 系统状态信息
    """
    from src.chat.memory_system.enhanced_memory_manager import enhanced_memory_manager

    return {
        "enabled": enhanced_memory_hooks.enabled,
        "enhanced_system_initialized": enhanced_memory_manager.is_initialized,
        "processed_messages_count": len(enhanced_memory_hooks.processed_messages),
        "system_type": "enhanced_memory_system",
    }


# 便捷函数
async def remember_message(
    message: str, user_id: str = "default_user", chat_id: str = "default_chat", context: dict[str, Any] | None = None
) -> bool:
    """
    便捷的记忆构建函数

    Args:
        message: 要记住的消息
        user_id: 用户ID
        chat_id: 聊天ID

    Returns:
        bool: 是否成功
    """
    import uuid

    message_id = str(uuid.uuid4())
    return await process_user_message_memory(
        message_content=message, user_id=user_id, chat_id=chat_id, message_id=message_id, context=context
    )


async def recall_memories(
    query: str,
    user_id: str = "default_user",
    chat_id: str = "default_chat",
    limit: int = 5,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    便捷的记忆检索函数

    Args:
        query: 查询文本
        user_id: 用户ID
        chat_id: 聊天ID
        limit: 返回数量限制

    Returns:
        Dict: 记忆信息
    """
    return await get_relevant_memories_for_response(
        query_text=query, user_id=user_id, chat_id=chat_id, limit=limit, extra_context=context
    )
