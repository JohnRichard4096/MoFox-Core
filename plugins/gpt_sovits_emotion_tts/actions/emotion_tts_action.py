"""
多情感 TTS 语音合成 Action

支持自动情感分析和语音风格切换。
"""

import tomllib
from pathlib import Path

from src.chat.utils.self_voice_cache import register_self_voice
from src.common.logger import get_logger
from src.plugin_system.base.base_action import BaseAction, ChatMode

from ..services.service_manager import get_service

logger = get_logger("gpt_sovits_emotion_tts.action")


def _get_available_emotions() -> list[str]:
    """动态读取配置文件，获取所有可用的情感名称"""
    try:
        plugin_file = Path(__file__).resolve()
        bot_root = plugin_file.parent.parent.parent.parent
        config_file = bot_root / "config" / "plugins" / "gpt_sovits_emotion_tts" / "config.toml"

        if not config_file.is_file():
            logger.warning("配置文件不存在，使用默认情感列表。")
            return ["neutral", "happy", "sad", "angry"]

        with open(config_file, "rb") as f:
            config = tomllib.load(f)
        styles_config = config.get("emotion_styles", [])
        
        if not isinstance(styles_config, list):
            return ["neutral"]

        emotion_names: list[str] = []
        for style in styles_config:
            if isinstance(style, dict):
                name = style.get("emotion_name")
                if isinstance(name, str) and name:
                    emotion_names.append(name)

        return emotion_names if emotion_names else ["neutral"]
    except Exception as e:
        logger.error(f"动态加载情感列表时出错: {e}")
        return ["neutral"]


# 获取可用情感列表
AVAILABLE_EMOTIONS = _get_available_emotions()
EMOTION_OPTIONS_DESC = ", ".join(f"'{e}'" for e in AVAILABLE_EMOTIONS)


class EmotionTTSAction(BaseAction):
    """
    多情感 TTS 语音合成动作
    
    支持自动分析文本情感并选择合适的语音风格，
    也可以手动指定情感。
    """

    action_name = "emotion_tts_action"
    action_description = "将文本转换为带有情感的语音并发送。支持自动情感分析或手动指定情感风格。"

    mode_enable = ChatMode.ALL
    parallel_action = False

    action_parameters = {
        "tts_text": {
            "type": "string",
            "description": "需要转换为语音并发送的完整、自然、适合口语的文本内容。必须是纯净的对话文本，不能包含括号内的动作描述或特殊符号。",
            "required": True
        },
        "emotion": {
            "type": "string",
            "description": f"语音的情感风格。可用选项: [{EMOTION_OPTIONS_DESC}]。如果不指定，将自动分析文本情感。根据对话的情感和上下文选择最合适的风格。",
            "required": False
        },
        "text_language": {
            "type": "string",
            "description": (
                "指定用于合成的语言模式。可用选项：\n"
                "- 'zh': 中文与英文混合 (推荐)\n"
                "- 'ja': 日文与英文混合\n"
                "- 'yue': 粤语与英文混合\n"
                "- 'ko': 韩文与英文混合\n"
                "- 'en': 纯英文\n"
                "- 'auto': 自动识别"
            ),
            "required": False
        }
    }

    action_require = [
        "调用此动作时，必须在 'tts_text' 参数中提供要合成语音的完整回复内容。",
        "当用户明确请求使用语音进行回复时，例如'发个语音听听'、'用语音说'等。",
        "当对话内容适合用语音表达，例如讲故事、念诗、撒娇或进行角色扮演时。",
        "在表达特殊情感（如安慰、鼓励、庆祝）的场景下，可以主动使用语音来增强感染力。",
        "可以通过 'emotion' 参数指定语音情感风格，如 'happy'（开心）、'sad'（悲伤）、'gentle'（温柔）等。",
        "如果不指定 'emotion' 参数，系统会自动分析文本情感并选择合适的风格。",
        "提供的文本必须是纯粹的对话，不能包含任何括号或方括号括起来的动作、表情、或场景描述。",
        "文本内容必须是纯净的口语文本，不要使用特殊符号（如 '♪', '～', '☆' 等）。",
        "所有句子和停顿必须只使用标准标点符号：'，'、'。'、'？'、'！'。"
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tts_service = None

    async def go_activate(self, llm_judge_model=None) -> bool:
        """
        判断此 Action 是否应该被激活。
        """
        # 条件1: 随机激活 (20%)
        if await self._random_activation(0.20):
            logger.info(f"{self.log_prefix} 随机激活成功 (20%)")
            return True

        # 条件2: 关键词激活
        keywords = [
            "发语音", "语音", "说句话", "用语音说", "听你", "听声音", "想听你", "想听声音",
            "讲个话", "说段话", "念一下", "读一下", "用嘴说", "说", "能发语音吗", "亲口",
            "用声音说", "语音回复"
        ]
        if await self._keyword_match(keywords):
            logger.info(f"{self.log_prefix} 关键词激活成功")
            return True

        # 条件3: LLM 判断激活
        if await self._llm_judge_activation(llm_judge_model=llm_judge_model):
            logger.info(f"{self.log_prefix} LLM 判断激活成功")
            return True

        logger.debug(f"{self.log_prefix} 所有激活条件均未满足，不激活")
        return False

    async def execute(self) -> tuple[bool, str]:
        """
        执行 Action 的核心逻辑
        """
        try:
            self.tts_service = get_service("emotion_tts")
            if not self.tts_service:
                logger.error(f"{self.log_prefix} EmotionTTSService 未注册或初始化失败")
                return False, "EmotionTTSService 未注册或初始化失败"

            # 获取参数
            text = self.action_data.get("tts_text", "").strip()
            emotion_hint = self.action_data.get("emotion")
            text_language = self.action_data.get("text_language")
            
            logger.info(f"{self.log_prefix} 接收到文本: '{text[:70]}...', 指定情感: {emotion_hint}, 语言: {text_language}")

            if not text:
                logger.warning(f"{self.log_prefix} 文本为空，静默处理")
                return False, "文本为空"

            # 获取聊天 ID（用于情绪联动）
            chat_id = None
            if hasattr(self, 'chat_stream') and self.chat_stream:
                chat_id = self.chat_stream.stream_id

            # 生成语音
            audio_b64, used_emotion = await self.tts_service.generate_voice(
                text=text,
                emotion_hint=emotion_hint,
                chat_id=chat_id,
                language_hint=text_language,
                auto_analyze=True
            )

            if audio_b64:
                # 注册到语音缓存
                register_self_voice(audio_b64, text)
                
                # 发送语音
                await self.send_custom(message_type="voice", content=audio_b64)
                
                logger.info(f"{self.log_prefix} 多情感语音发送成功，使用情感: {used_emotion}")
                await self.store_action_info(
                    action_prompt_display=f"将文本转换为带有'{used_emotion}'情感的语音并发送",
                    action_done=True
                )
                return True, f"成功生成并发送语音，情感: {used_emotion}，文本长度: {len(text)}字符"
            else:
                logger.error(f"{self.log_prefix} TTS服务未能返回音频数据")
                await self.store_action_info(
                    action_prompt_display="语音合成失败: TTS服务未能返回音频数据",
                    action_done=False
                )
                return False, "语音合成失败"

        except Exception as e:
            logger.error(f"{self.log_prefix} 语音合成过程中发生错误: {e!s}")
            await self.store_action_info(
                action_prompt_display=f"语音合成失败: {e!s}",
                action_done=False
            )
            return False, f"语音合成出错: {e!s}"
