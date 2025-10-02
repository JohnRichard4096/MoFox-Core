"""
兴趣度系统模块
提供机器人兴趣标签和智能匹配功能
"""

from src.common.data_models.bot_interest_data_model import BotInterestTag, BotPersonalityInterests, InterestMatchResult

from .bot_interest_manager import BotInterestManager, bot_interest_manager

__all__ = [
    "BotInterestManager",
    "BotInterestTag",
    "BotPersonalityInterests",
    "InterestMatchResult",
    "bot_interest_manager",
]
