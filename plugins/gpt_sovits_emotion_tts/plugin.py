"""
GPT-SoVITS 多情感语音合成插件

支持：
- 多情感参考音频配置
- 自动情感分析和风格选择
- 与机器人情绪系统联动
- 多种语言支持
"""

import tomllib
from pathlib import Path
from typing import Any, ClassVar

from src.common.logger import get_logger
from src.plugin_system import BasePlugin, register_plugin
from src.plugin_system.base.component_types import PermissionNodeField
from src.plugin_system.base.config_types import ConfigField

from .services.emotion_analyzer import EmotionAnalyzer
from .services.tts_service import EmotionTTSService
from .services.service_manager import register_service
from .actions.emotion_tts_action import EmotionTTSAction
from .commands.emotion_tts_command import EmotionTTSCommand

logger = get_logger("gpt_sovits_emotion_tts")


@register_plugin
class GPTSoVITSEmotionTTSPlugin(BasePlugin):
    """
    GPT-SoVITS 多情感语音合成插件
    
    特性：
    - 基于情感分析自动选择语音风格
    - 支持多种情感预设（开心、悲伤、愤怒、平静等）
    - 与机器人情绪系统联动
    - 支持手动指定情感风格
    """

    plugin_name = "gpt_sovits_emotion_tts"
    plugin_description = "基于GPT-SoVITS的多情感语音合成插件"
    plugin_version = "1.0.0"
    plugin_author = "MoFox Studio"
    enable_plugin = True
    config_file_name = "config.toml"
    dependencies: ClassVar[list[str]] = []

    permission_nodes: ClassVar[list[PermissionNodeField]] = [
        PermissionNodeField(node_name="command.use", description="是否可以使用 /etts 命令"),
        PermissionNodeField(node_name="command.list_emotions", description="是否可以查看可用情感列表"),
    ]

    config_schema: ClassVar[dict] = {
        "plugin": {
            "enable": ConfigField(type=bool, default=True, description="是否启用插件"),
        },
        "components": {
            "action_enabled": ConfigField(type=bool, default=True, description="是否启用Action组件"),
            "command_enabled": ConfigField(type=bool, default=True, description="是否启用命令组件"),
        },
    }

    config_section_descriptions: ClassVar[dict] = {
        "plugin": "插件基本配置",
        "components": "组件启用控制",
        "tts": "TTS语音合成基础配置",
        "tts_advanced": "TTS高级参数配置",
        "emotion_styles": "情感风格配置（每个分组为一种情感）",
        "emotion_analysis": "情感分析配置",
        "spatial_effects": "空间音效配置"
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tts_service: EmotionTTSService | None = None
        self.emotion_analyzer: EmotionAnalyzer | None = None

    def _create_default_config(self, config_file: Path):
        """
        如果配置文件不存在，则创建一个默认的配置文件。
        """
        if config_file.is_file():
            return

        logger.info(f"配置文件不存在，正在创建默认配置文件于: {config_file}")

        default_config_content = '''# GPT-SoVITS 多情感语音合成插件配置
# ============================================

# 插件基础配置
[plugin]
enable = true

# 触发关键词列表
keywords = [
    "发语音", "语音", "说句话", "用语音说", "听你", "听声音", "想听你", "想听声音",
    "讲个话", "说段话", "念一下", "读一下", "用嘴说", "说", "能发语音吗", "亲口",
    "用声音说", "语音回复"
]

# 组件启用控制
[components]
action_enabled = true
command_enabled = true

# TTS 语音合成基础配置
[tts]
# GPT-SoVITS 服务器地址
server = "http://127.0.0.1:9880"
# 请求超时时间（秒）
timeout = 180
# 最大文本长度
max_text_length = 1000

# 情感分析配置
[emotion_analysis]
# 是否启用自动情感分析
enabled = true
# 是否使用机器人情绪系统的情绪状态作为参考
use_bot_mood = true
# 情感分析使用的模型（留空使用默认模型）
model = ""

# TTS 高级参数配置
[tts_advanced]
media_type = "wav"
top_k = 9
top_p = 0.8
temperature = 0.8
batch_size = 6
batch_threshold = 0.75
text_split_method = "cut5"
repetition_penalty = 1.4
sample_steps = 150
super_sampling = true

# 空间音效配置
[spatial_effects]
# 是否启用空间音效处理
enabled = false
# 是否启用标准混响效果
reverb_enabled = false
room_size = 0.2
damping = 0.6
wet_level = 0.3
dry_level = 0.8
width = 1.0
# 是否启用卷积混响
convolution_enabled = false
convolution_mix = 0.7

# ============================================
# 情感风格配置
# ============================================
# 每个 [[emotion_styles]] 代表一种情感的语音配置
# emotion_name: 情感的唯一标识符（必须有一个 "neutral" 作为默认）
# display_name: 显示名称
# keywords: 触发该情感的关键词列表
# refer_wav_path: 参考音频路径
# prompt_text: 参考音频对应的文本
# prompt_language: 参考音频语言
# gpt_weights: GPT 模型路径（可选，留空使用全局配置）
# sovits_weights: SoVITS 模型路径（可选，留空使用全局配置）
# speed_factor: 语速因子（1.0为正常速度）

# 中性/平静 - 默认情感
[[emotion_styles]]
emotion_name = "neutral"
display_name = "平静"
keywords = ["平静", "普通", "正常", "一般"]
refer_wav_path = "path/to/neutral_reference.wav"
prompt_text = "这是一段平静的参考音频文本，请替换为您的实际内容。"
prompt_language = "zh"
gpt_weights = ""
sovits_weights = ""
speed_factor = 1.0

# 开心/愉快
[[emotion_styles]]
emotion_name = "happy"
display_name = "开心"
keywords = ["开心", "高兴", "愉快", "兴奋", "快乐", "欢乐", "喜悦"]
refer_wav_path = "path/to/happy_reference.wav"
prompt_text = "这是一段开心的参考音频文本，请替换为您的实际内容。"
prompt_language = "zh"
gpt_weights = ""
sovits_weights = ""
speed_factor = 1.05

# 悲伤/难过
[[emotion_styles]]
emotion_name = "sad"
display_name = "悲伤"
keywords = ["悲伤", "难过", "伤心", "失落", "沮丧", "低落", "忧郁"]
refer_wav_path = "path/to/sad_reference.wav"
prompt_text = "这是一段悲伤的参考音频文本，请替换为您的实际内容。"
prompt_language = "zh"
gpt_weights = ""
sovits_weights = ""
speed_factor = 0.9

# 愤怒/生气
[[emotion_styles]]
emotion_name = "angry"
display_name = "愤怒"
keywords = ["愤怒", "生气", "恼火", "不满", "气愤", "暴怒"]
refer_wav_path = "path/to/angry_reference.wav"
prompt_text = "这是一段愤怒的参考音频文本，请替换为您的实际内容。"
prompt_language = "zh"
gpt_weights = ""
sovits_weights = ""
speed_factor = 1.1

# 惊讶/意外
[[emotion_styles]]
emotion_name = "surprised"
display_name = "惊讶"
keywords = ["惊讶", "震惊", "意外", "吃惊", "惊奇", "诧异"]
refer_wav_path = "path/to/surprised_reference.wav"
prompt_text = "这是一段惊讶的参考音频文本，请替换为您的实际内容。"
prompt_language = "zh"
gpt_weights = ""
sovits_weights = ""
speed_factor = 1.15

# 害怕/恐惧
[[emotion_styles]]
emotion_name = "fearful"
display_name = "害怕"
keywords = ["害怕", "恐惧", "担心", "紧张", "焦虑", "不安"]
refer_wav_path = "path/to/fearful_reference.wav"
prompt_text = "这是一段害怕的参考音频文本，请替换为您的实际内容。"
prompt_language = "zh"
gpt_weights = ""
sovits_weights = ""
speed_factor = 1.0

# 厌恶/讨厌
[[emotion_styles]]
emotion_name = "disgusted"
display_name = "厌恶"
keywords = ["厌恶", "讨厌", "反感", "嫌弃", "恶心"]
refer_wav_path = "path/to/disgusted_reference.wav"
prompt_text = "这是一段厌恶的参考音频文本，请替换为您的实际内容。"
prompt_language = "zh"
gpt_weights = ""
sovits_weights = ""
speed_factor = 0.95

# 温柔/撒娇
[[emotion_styles]]
emotion_name = "gentle"
display_name = "温柔"
keywords = ["温柔", "撒娇", "软萌", "可爱", "甜美", "娇嗔"]
refer_wav_path = "path/to/gentle_reference.wav"
prompt_text = "这是一段温柔的参考音频文本，请替换为您的实际内容。"
prompt_language = "zh"
gpt_weights = ""
sovits_weights = ""
speed_factor = 0.95

# 严肃/认真
[[emotion_styles]]
emotion_name = "serious"
display_name = "严肃"
keywords = ["严肃", "认真", "庄重", "正经", "严谨"]
refer_wav_path = "path/to/serious_reference.wav"
prompt_text = "这是一段严肃的参考音频文本，请替换为您的实际内容。"
prompt_language = "zh"
gpt_weights = ""
sovits_weights = ""
speed_factor = 0.95

'''

        try:
            config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(config_file, "w", encoding="utf-8") as f:
                f.write(default_config_content.strip())
            logger.info("默认配置文件创建成功。")
        except Exception as e:
            logger.error(f"创建默认配置文件失败: {e}")

    def _get_config_wrapper(self, key: str, default: Any = None) -> Any:
        """
        配置获取的包装器，用于获取动态表（如 emotion_styles）和未在 schema 中定义的节。
        """
        manual_load_keys = ["emotion_styles", "spatial_effects", "tts_advanced", "tts", "emotion_analysis"]
        top_key = key.split(".")[0]

        if top_key in manual_load_keys:
            try:
                plugin_file = Path(__file__).resolve()
                bot_root = plugin_file.parent.parent.parent
                config_file = bot_root / "config" / "plugins" / self.plugin_name / self.config_file_name

                if not config_file.is_file():
                    logger.error(f"配置文件不存在: {config_file}")
                    return default

                with open(config_file, "rb") as f:
                    full_config = tomllib.load(f)

                # 支持点状路径访问
                value = full_config
                for k in key.split("."):
                    if isinstance(value, dict):
                        value = value.get(k)
                    else:
                        return default

                return value if value is not None else default

            except Exception as e:
                logger.error(f"加载配置 '{key}' 失败: {e}")
                return default

        return self.get_config(key, default)

    async def on_plugin_loaded(self):
        """
        插件加载完成后的回调，初始化服务。
        """
        logger.info("初始化 GPT-SoVITS 多情感语音合成插件...")

        plugin_file = Path(__file__).resolve()
        bot_root = plugin_file.parent.parent.parent
        config_file = bot_root / "config" / "plugins" / self.plugin_name / self.config_file_name
        self._create_default_config(config_file)

        # 初始化情感分析器
        self.emotion_analyzer = EmotionAnalyzer(self._get_config_wrapper)
        register_service("emotion_analyzer", self.emotion_analyzer)
        
        # 初始化 TTS 服务
        self.tts_service = EmotionTTSService(self._get_config_wrapper, self.emotion_analyzer)
        register_service("emotion_tts", self.tts_service)
        
        logger.info("GPT-SoVITS 多情感语音合成插件初始化完成。")
        if self.tts_service:
            logger.info(f"已加载情感风格: {list(self.tts_service.emotion_styles.keys())}")

    def get_plugin_components(self):
        """
        返回插件包含的组件列表。
        """
        components = []
        if self.get_config("components.action_enabled", True):
            components.append((EmotionTTSAction.get_action_info(), EmotionTTSAction))
        if self.get_config("components.command_enabled", True):
            components.append((EmotionTTSCommand.get_plus_command_info(), EmotionTTSCommand))
        return components
