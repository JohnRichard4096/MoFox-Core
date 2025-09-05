"""
跨群聊上下文API
"""

import time
from typing import Dict, Any, Optional, List

from src.common.logger import get_logger
from src.config.config import global_config
from src.chat.utils.chat_message_builder import (
    get_raw_msg_before_timestamp_with_chat,
    build_readable_messages_with_id,
)
from src.chat.message_receive.chat_stream import get_chat_manager, ChatStream

logger = get_logger("cross_context_api")


def get_context_groups(chat_id: str) -> Optional[List[str]]:
    """
    获取当前群聊所在的共享组的其他群聊ID
    """
    current_stream = get_chat_manager().get_stream(chat_id)
    if not current_stream or not current_stream.group_info:
        return None

    try:
        current_chat_raw_id = current_stream.group_info.group_id
    except Exception as e:
        logger.error(f"获取群聊ID失败: {e}")
        return None

    for group in global_config.cross_context.groups:
        if str(current_chat_raw_id) in group.chat_ids:
            return [chat_id for chat_id in group.chat_ids if chat_id != str(current_chat_raw_id)]

    return None


async def build_cross_context_normal(chat_stream: ChatStream, other_chat_raw_ids: List[str]) -> str:
    """
    构建跨群聊上下文 (Normal模式)
    """
    cross_context_messages = []
    for chat_raw_id in other_chat_raw_ids:
        stream_id = get_chat_manager().get_stream_id(chat_stream.platform, chat_raw_id, is_group=True)
        if not stream_id:
            continue

        try:
            messages = get_raw_msg_before_timestamp_with_chat(
                chat_id=stream_id,
                timestamp=time.time(),
                limit=5,  # 可配置
            )
            if messages:
                chat_name = get_chat_manager().get_stream_name(stream_id) or stream_id
                formatted_messages, _ = build_readable_messages_with_id(messages, timestamp_mode="relative")
                cross_context_messages.append(f'[以下是来自"{chat_name}"的近期消息]\n{formatted_messages}')
        except Exception as e:
            logger.error(f"获取群聊{chat_raw_id}的消息失败: {e}")
            continue

    if not cross_context_messages:
        return ""

    return "# 跨群上下文参考\n" + "\n\n".join(cross_context_messages) + "\n"


async def build_cross_context_s4u(
    chat_stream: ChatStream, other_chat_raw_ids: List[str], target_user_info: Optional[Dict[str, Any]]
) -> str:
    """
    构建跨群聊上下文 (S4U模式)
    """
    cross_context_messages = []
    if target_user_info:
        user_id = target_user_info.get("user_id")

        if user_id:
            for chat_raw_id in other_chat_raw_ids:
                stream_id = get_chat_manager().get_stream_id(
                    chat_stream.platform, chat_raw_id, is_group=True
                )
                if not stream_id:
                    continue

                try:
                    messages = get_raw_msg_before_timestamp_with_chat(
                        chat_id=stream_id,
                        timestamp=time.time(),
                        limit=20,  # 获取更多消息以供筛选
                    )
                    user_messages = [msg for msg in messages if msg.get("user_id") == user_id][
                        -5:
                    ]  # 筛选并取最近5条

                    if user_messages:
                        chat_name = get_chat_manager().get_stream_name(stream_id) or stream_id
                        user_name = (
                            target_user_info.get("person_name")
                            or target_user_info.get("user_nickname")
                            or user_id
                        )
                        formatted_messages, _ = build_readable_messages_with_id(
                            user_messages, timestamp_mode="relative"
                        )
                        cross_context_messages.append(
                            f'[以下是"{user_name}"在"{chat_name}"的近期发言]\n{formatted_messages}'
                        )
                except Exception as e:
                    logger.error(f"获取用户{user_id}在群聊{chat_raw_id}的消息失败: {e}")
                    continue

    if not cross_context_messages:
        return ""

    return "# 跨群上下文参考\n" + "\n\n".join(cross_context_messages) + "\n"