"""
共享提示词工具模块 - 消除重复代码
提供统一的工具函数供DefaultReplyer和SmartPrompt使用
"""

import re
import time
from typing import Dict, Any, Optional, Tuple

from src.common.logger import get_logger
from src.config.config import global_config
from src.chat.message_receive.chat_stream import get_chat_manager
from src.person_info.person_info import get_person_info_manager
from src.plugin_system.apis import cross_context_api
logger = get_logger("prompt_utils")


class PromptUtils:
    """提示词工具类 - 提供共享功能，移除缓存相关功能和依赖检查"""

    @staticmethod
    def parse_reply_target(target_message: str) -> Tuple[str, str]:
        """
        解析回复目标消息 - 统一实现

        Args:
            target_message: 目标消息，格式为 "发送者:消息内容" 或 "发送者：消息内容"

        Returns:
            Tuple[str, str]: (发送者名称, 消息内容)
        """
        sender = ""
        target = ""

        # 添加None检查，防止NoneType错误
        if target_message is None:
            return sender, target

        if ":" in target_message or "：" in target_message:
            # 使用正则表达式匹配中文或英文冒号
            parts = re.split(pattern=r"[:：]", string=target_message, maxsplit=1)
            if len(parts) == 2:
                sender = parts[0].strip()
                target = parts[1].strip()
        return sender, target

    @staticmethod
    async def build_relation_info(chat_id: str, reply_to: str) -> str:
        """
        构建关系信息 - 统一实现

        Args:
            chat_id: 聊天ID
            reply_to: 回复目标字符串

        Returns:
            str: 关系信息字符串
        """
        if not global_config.relationship.enable_relationship:
            return ""

        from src.person_info.relationship_fetcher import relationship_fetcher_manager

        relationship_fetcher = relationship_fetcher_manager.get_fetcher(chat_id)

        if not reply_to:
            return ""
        sender, text = PromptUtils.parse_reply_target(reply_to)
        if not sender or not text:
            return ""

        # 获取用户ID
        person_info_manager = get_person_info_manager()
        person_id = person_info_manager.get_person_id_by_person_name(sender)
        if not person_id:
            logger.warning(f"未找到用户 {sender} 的ID，跳过信息提取")
            return f"你完全不认识{sender}，不理解ta的相关信息。"

        return await relationship_fetcher.build_relation_info(person_id, points_num=5)

    @staticmethod
    async def build_cross_context(
            chat_id: str, target_user_info: Optional[Dict[str, Any]], current_prompt_mode: str
        ) -> str:
            """
            构建跨群聊上下文 - 统一实现，完全继承DefaultReplyer功能
            """
            if not global_config.cross_context.enable:
                return ""

            other_chat_raw_ids = cross_context_api.get_context_groups(chat_id)
            if not other_chat_raw_ids:
                return ""

            chat_stream = get_chat_manager().get_stream(chat_id)
            if not chat_stream:
                return ""

            if current_prompt_mode == "normal":
                return await cross_context_api.build_cross_context_normal(chat_stream, other_chat_raw_ids)
            elif current_prompt_mode == "s4u":
                return await cross_context_api.build_cross_context_s4u(chat_stream, other_chat_raw_ids, target_user_info)

            return ""

    @staticmethod
    def parse_reply_target_id(reply_to: str) -> str:
        """
        解析回复目标中的用户ID

        Args:
            reply_to: 回复目标字符串

        Returns:
            str: 用户ID
        """
        if not reply_to:
            return ""

        # 复用parse_reply_target方法的逻辑
        sender, _ = PromptUtils.parse_reply_target(reply_to)
        if not sender:
            return ""

        # 获取用户ID
        person_info_manager = get_person_info_manager()
        person_id = person_info_manager.get_person_id_by_person_name(sender)
        if person_id:
            user_id = person_info_manager.get_value_sync(person_id, "user_id")
            return str(user_id) if user_id else ""

        return ""
