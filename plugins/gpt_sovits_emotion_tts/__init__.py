"""
GPT-SoVITS 多情感语音合成插件

基于 GPT-SoVITS 的语音合成插件，支持：
- 多种情感风格（开心、悲伤、愤怒、温柔等）
- 自动情感分析
- 与机器人情绪系统联动
- 多语言支持
"""

from .plugin import GPTSoVITSEmotionTTSPlugin

__all__ = ["GPTSoVITSEmotionTTSPlugin"]
