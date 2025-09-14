# -*- coding: utf-8 -*-
"""
表情包发送历史记录模块
"""
import os
from typing import List, Dict
from collections import deque

from src.common.logger import get_logger

logger = get_logger("EmojiHistory")

MAX_HISTORY_SIZE = 5  # 每个聊天会话最多保留最近5条表情历史

# 使用一个全局字典在内存中存储历史记录
# 键是 chat_id，值是一个 deque 对象
_history_cache: Dict[str, deque] = {}


def add_emoji_to_history(chat_id: str, emoji_description: str):
    """
    将发送的表情包添加到内存历史记录中。

    :param chat_id: 聊天会话ID (例如 "private_12345" 或 "group_67890")
    :param emoji_description: 发送的表情包的描述
    """
    if not chat_id or not emoji_description:
        return
    
    # 如果当前聊天还没有历史记录，则创建一个新的 deque
    if chat_id not in _history_cache:
        _history_cache[chat_id] = deque(maxlen=MAX_HISTORY_SIZE)
        
    # 添加新表情到历史记录
    history = _history_cache[chat_id]
    history.append(emoji_description)
    
    logger.debug(f"已将表情 '{emoji_description}' 添加到聊天 {chat_id} 的内存历史中")


def get_recent_emojis(chat_id: str, limit: int = 5) -> List[str]:
    """
    从内存中获取最近发送的表情包描述列表。

    :param chat_id: 聊天会话ID
    :param limit: 获取的表情数量上限
    :return: 最近发送的表情包描述列表
    """
    if not chat_id or chat_id not in _history_cache:
        return []

    history = _history_cache[chat_id]
    
    # 从 deque 的右侧（即最近添加的）开始取
    num_to_get = min(limit, len(history))
    recent_emojis = [history[-i] for i in range(1, num_to_get + 1)]
    
    logger.debug(f"为聊天 {chat_id} 从内存中获取到最近 {len(recent_emojis)} 个表情: {recent_emojis}")
    return recent_emojis
