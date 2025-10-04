"""
兴趣度系统模块
提供机器人兴趣标签和智能匹配功能，以及消息兴趣值计算功能
"""

from src.common.data_models.bot_interest_data_model import BotInterestTag, BotPersonalityInterests, InterestMatchResult

from .bot_interest_manager import BotInterestManager, bot_interest_manager
from .interest_manager import InterestManager, get_interest_manager

__all__ = [
    # 机器人兴趣标签管理
    "BotInterestManager",
    "BotInterestTag",
    "BotPersonalityInterests",
    "InterestMatchResult",
    "bot_interest_manager",

    # 消息兴趣值计算管理
    "InterestManager",
    "get_interest_manager",
]
