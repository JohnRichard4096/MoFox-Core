"""
情感分析服务

用于分析文本情感并选择合适的语音风格。
支持：
- 基于关键词的简单情感识别
- 基于 LLM 的深度情感分析
- 与机器人情绪系统联动
"""

from collections.abc import Callable
from typing import Any

from src.common.logger import get_logger

logger = get_logger("gpt_sovits_emotion_tts.emotion_analyzer")

# 情感类型映射
EMOTION_KEYWORDS = {
    "happy": ["开心", "高兴", "愉快", "兴奋", "快乐", "欢乐", "喜悦", "太棒了", "好开心", "哈哈", "嘻嘻", "耶"],
    "sad": ["悲伤", "难过", "伤心", "失落", "沮丧", "低落", "忧郁", "好难过", "唉", "呜呜", "哭", "555"],
    "angry": ["愤怒", "生气", "恼火", "不满", "气愤", "暴怒", "可恶", "混蛋", "讨厌", "烦死了"],
    "surprised": ["惊讶", "震惊", "意外", "吃惊", "惊奇", "诧异", "天哪", "我的天", "啊", "哇", "居然"],
    "fearful": ["害怕", "恐惧", "担心", "紧张", "焦虑", "不安", "可怕", "吓死", "慌"],
    "disgusted": ["厌恶", "讨厌", "反感", "嫌弃", "恶心", "呕", "好烦"],
    "gentle": ["温柔", "撒娇", "软萌", "可爱", "甜美", "娇嗔", "嘛", "嘤嘤", "人家", "呐"],
    "serious": ["严肃", "认真", "庄重", "正经", "严谨", "注意", "重要", "必须"],
    "neutral": ["平静", "普通", "正常", "一般"]
}

# 情绪状态到情感的映射
MOOD_TO_EMOTION = {
    "感觉很平静": "neutral",
    "感觉很开心": "happy",
    "感觉很愉快": "happy",
    "感觉很兴奋": "happy",
    "感觉很难过": "sad",
    "感觉很伤心": "sad",
    "感觉很沮丧": "sad",
    "感觉很生气": "angry",
    "感觉很愤怒": "angry",
    "感觉很惊讶": "surprised",
    "感觉很害怕": "fearful",
    "感觉很紧张": "fearful",
    "感觉很厌恶": "disgusted",
    "感觉很温柔": "gentle",
    "感觉很严肃": "serious",
}


class EmotionAnalyzer:
    """情感分析器"""

    def __init__(self, get_config_func: Callable[[str, Any], Any]):
        self.get_config = get_config_func
        self._load_config()

    def _load_config(self) -> None:
        """加载配置"""
        try:
            emotion_config = self.get_config("emotion_analysis", {})
            self.enabled = emotion_config.get("enabled", True)
            self.use_bot_mood = emotion_config.get("use_bot_mood", True)
            self.model = emotion_config.get("model", "")
            
            # 加载情感风格配置中的关键词
            self.emotion_keywords = EMOTION_KEYWORDS.copy()
            emotion_styles = self.get_config("emotion_styles", [])
            for style in emotion_styles:
                if isinstance(style, dict):
                    emotion_name = style.get("emotion_name")
                    keywords = style.get("keywords", [])
                    if emotion_name and keywords:
                        if emotion_name in self.emotion_keywords:
                            self.emotion_keywords[emotion_name].extend(keywords)
                        else:
                            self.emotion_keywords[emotion_name] = keywords
            
            logger.info(f"情感分析器配置加载完成，启用状态: {self.enabled}")
        except Exception as e:
            logger.error(f"情感分析器配置加载失败: {e}")
            self.enabled = True
            self.use_bot_mood = True
            self.model = ""
            self.emotion_keywords = EMOTION_KEYWORDS.copy()

    def analyze_by_keywords(self, text: str) -> tuple[str, float]:
        """
        基于关键词分析文本情感
        
        Args:
            text: 要分析的文本
            
        Returns:
            (情感名称, 置信度)
        """
        if not text:
            return "neutral", 0.5

        text_lower = text.lower()
        emotion_scores: dict[str, int] = {}
        
        for emotion, keywords in self.emotion_keywords.items():
            score = 0
            for keyword in keywords:
                if keyword.lower() in text_lower:
                    score += 1
            if score > 0:
                emotion_scores[emotion] = score

        if not emotion_scores:
            return "neutral", 0.5

        # 找出得分最高的情感
        best_emotion = max(emotion_scores, key=lambda k: emotion_scores[k])
        max_score = emotion_scores[best_emotion]
        
        # 计算置信度（基于匹配的关键词数量）
        confidence = min(0.5 + max_score * 0.15, 0.95)
        
        return best_emotion, confidence

    async def analyze_by_llm(self, text: str, available_emotions: list[str]) -> tuple[str, float]:
        """
        使用 LLM 分析文本情感
        
        Args:
            text: 要分析的文本
            available_emotions: 可用的情感列表
            
        Returns:
            (情感名称, 置信度)
        """
        try:
            from src.config.config import model_config
            from src.llm_models.utils_model import LLMRequest
            
            # 创建情感分析请求
            emotion_list_str = ", ".join(available_emotions)
            prompt = f"""请分析以下文本所表达的情感，从给定的情感列表中选择最合适的一个。

可用情感列表: {emotion_list_str}

待分析文本: {text}

请只输出一个情感名称，不要输出任何其他内容。如果无法确定，请输出 "neutral"。"""

            llm_request = LLMRequest(
                model_set=model_config.model_task_config.emotion if not self.model else self.model,
                request_type="emotion_analysis"
            )
            
            result, _ = await llm_request.generate_response_async(prompt)
            
            if result:
                result = result.strip().lower()
                # 尝试匹配情感
                for emotion in available_emotions:
                    if emotion.lower() in result or result in emotion.lower():
                        return emotion, 0.85
            
            return "neutral", 0.5
            
        except Exception as e:
            logger.error(f"LLM 情感分析失败: {e}")
            return "neutral", 0.5

    async def get_bot_mood_emotion(self, chat_id: str) -> str | None:
        """
        获取机器人当前对该聊天的情绪状态对应的情感
        
        Args:
            chat_id: 聊天 ID
            
        Returns:
            情感名称，如果无法获取则返回 None
        """
        if not self.use_bot_mood:
            return None
            
        try:
            from src.mood.mood_manager import mood_manager
            
            # 使用 get_mood_by_chat_id 方法获取情绪
            mood = mood_manager.get_mood_by_chat_id(chat_id)
            if mood:
                mood_state = mood.mood_state
                
                # 尝试直接映射
                if mood_state in MOOD_TO_EMOTION:
                    return MOOD_TO_EMOTION[mood_state]
                
                # 尝试部分匹配
                for key, emotion in MOOD_TO_EMOTION.items():
                    if key in mood_state or mood_state in key:
                        return emotion
                
                # 使用关键词分析情绪状态
                emotion, _ = self.analyze_by_keywords(mood_state)
                return emotion
                
        except Exception:
            logger.debug(f"获取机器人情绪状态失败: chat_id={chat_id}")
        
        return None

    async def analyze_emotion(
        self,
        text: str,
        chat_id: str | None = None,
        available_emotions: list[str] | None = None,
        use_llm: bool = False
    ) -> tuple[str, float]:
        """
        综合分析文本情感
        
        Args:
            text: 要分析的文本
            chat_id: 聊天 ID（用于获取机器人情绪）
            available_emotions: 可用的情感列表
            use_llm: 是否使用 LLM 进行分析
            
        Returns:
            (情感名称, 置信度)
        """
        if not self.enabled:
            return "neutral", 1.0
        
        if available_emotions is None:
            available_emotions = list(self.emotion_keywords.keys())
        
        # 1. 首先尝试获取机器人情绪状态
        if chat_id:
            bot_emotion = await self.get_bot_mood_emotion(chat_id)
            if bot_emotion and bot_emotion in available_emotions:
                logger.info(f"使用机器人情绪状态: {bot_emotion}")
                return bot_emotion, 0.8
        
        # 2. 基于关键词分析
        keyword_emotion, keyword_confidence = self.analyze_by_keywords(text)
        
        # 如果关键词置信度足够高，直接返回
        if keyword_confidence >= 0.8:
            logger.info(f"关键词分析结果: {keyword_emotion} (置信度: {keyword_confidence})")
            return keyword_emotion, keyword_confidence
        
        # 3. 如果启用 LLM 分析且关键词置信度不够高
        if use_llm and keyword_confidence < 0.7:
            llm_emotion, llm_confidence = await self.analyze_by_llm(text, available_emotions)
            
            # 如果 LLM 结果置信度更高，使用 LLM 结果
            if llm_confidence > keyword_confidence:
                logger.info(f"LLM 分析结果: {llm_emotion} (置信度: {llm_confidence})")
                return llm_emotion, llm_confidence
        
        # 确保返回的情感在可用列表中
        if keyword_emotion not in available_emotions:
            keyword_emotion = "neutral" if "neutral" in available_emotions else available_emotions[0]
        
        logger.info(f"最终情感分析结果: {keyword_emotion} (置信度: {keyword_confidence})")
        return keyword_emotion, keyword_confidence
