"""
TTS Voice 插件 - 重构版
"""
from pathlib import Path
from typing import Any, ClassVar

import toml

from src.common.logger import get_logger
from src.plugin_system import BasePlugin, ComponentInfo, register_plugin
from src.plugin_system.base.component_types import PermissionNodeField

from .actions.tts_action import TTSVoiceAction
from .commands.tts_command import TTSVoiceCommand
from .services.manager import register_service
from .services.tts_service import TTSService

logger = get_logger("tts_voice_plugin")


@register_plugin
class TTSVoicePlugin(BasePlugin):
    """
    GPT-SoVITS 语音合成插件 - 重构版
    """

    plugin_name = "tts_voice_plugin"
    plugin_description = "基于GPT-SoVITS的文本转语音插件（重构版）"
    plugin_version = "3.1.2"
    plugin_author = "Kilo Code & 靚仔"
    enable_plugin = True
    config_file_name = "config.toml"
    dependencies: ClassVar[list[str]] = []

    permission_nodes: ClassVar[list[PermissionNodeField]] = [
        PermissionNodeField(node_name="command.use", description="是否可以使用 /tts 命令"),
    ]

    config_schema: ClassVar[dict] = {}

    config_section_descriptions: ClassVar[dict] = {
        "plugin": "插件基本配置",
        "components": "组件启用控制",
        "tts": "TTS语音合成基础配置",
        "tts_advanced": "TTS高级参数配置（语速、采样、批处理等）",
        "tts_styles": "TTS风格参数配置（每个分组为一种风格）"
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tts_service = None

    def _create_default_config(self, config_file: Path):
        """
        如果配置文件不存在，则创建一个默认的配置文件。
        """
        if config_file.is_file():
            return

        logger.info(f"TTS 配置文件不存在，正在创建默认配置文件于: {config_file}")

        default_config_content = """# 插件基础配置
[plugin]
enable = true
keywords = [
    "发语音", "语音", "说句话", "用语音说", "听你", "听声音", "想听你", "想听声音",
    "讲个话", "说段话", "念一下", "读一下", "用嘴说", "说", "能发语音吗","亲口"
]

# 组件启用控制
[components]
action_enabled = true
command_enabled = true

# TTS 语音合成基础配置
[tts]
server = "http://127.0.0.1:9880"
timeout = 180
max_text_length = 1000

# TTS 风格参数配置
# 每个 [[tts_styles]] 代表一个独立的语音风格配置
[[tts_styles]]
# 风格的唯一标识符，必须有一个名为 "default"
style_name = "default"
# 显示名称
name = "默认"
# 参考音频路径
refer_wav_path = "C:/path/to/your/reference.wav"
# 参考音频文本
prompt_text = "这是一个示例文本，请替换为您自己的参考音频文本。"
# 参考音频语言
prompt_language = "zh"
# GPT 模型路径
gpt_weights = "C:/path/to/your/gpt_weights.ckpt"
# SoVITS 模型路径
sovits_weights = "C:/path/to/your/sovits_weights.pth"
# 语速
speed_factor = 1.0

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

# 混响的房间大小 (建议范围 0.0-1.0)
room_size = 0.2

# 混响的阻尼/高频衰减 (建议范围 0.0-1.0)
damping = 0.6

# 混响的湿声（效果声）比例 (建议范围 0.0-1.0)
wet_level = 0.3

# 混响的干声（原声）比例 (建议范围 0.0-1.0)
dry_level = 0.8

# 混响的立体声宽度 (建议范围 0.0-1.0)
width = 1.0

# 是否启用卷积混响（需要assets/small_room_ir.wav文件）
convolution_enabled = false

# 卷积混响的干湿比 (建议范围 0.0-1.0)
convolution_mix = 0.7
"""

        try:
            config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(config_file, "w", encoding="utf-8") as f:
                f.write(default_config_content.strip())
            logger.info("默认 TTS 配置文件创建成功。")
        except Exception as e:
            logger.error(f"创建默认 TTS 配置文件失败: {e}")

    def _get_config_wrapper(self, key: str, default: Any = None) -> Any:
        """
        配置获取的包装器，用于解决 get_config 无法直接获取动态表（如 tts_styles）和未在 schema 中定义的节的问题。
        由于插件系统的 schema 为空时不会加载未定义的键，这里手动读取配置文件以获取所需配置。
        """
        # 需要手动加载的顶级配置节
        manual_load_keys = ["tts_styles", "spatial_effects", "tts_advanced", "tts"]
        top_key = key.split(".")[0]

        if top_key in manual_load_keys:
            try:
                plugin_file = Path(__file__).resolve()
                bot_root = plugin_file.parent.parent.parent.parent.parent
                config_file = bot_root / "config" / "plugins" / self.plugin_name / self.config_file_name

                if not config_file.is_file():
                    logger.error(f"TTS config file not found at robustly constructed path: {config_file}")
                    return default

                full_config = toml.loads(config_file.read_text(encoding="utf-8"))

                # 支持点状路径访问
                value = full_config
                for k in key.split("."):
                    if isinstance(value, dict):
                        value = value.get(k)
                    else:
                        return default

                return value if value is not None else default

            except Exception as e:
                logger.error(f"Failed to manually load '{key}' from config: {e}")
                return default

        return self.get_config(key, default)

    async def on_plugin_loaded(self):
        """
        插件加载完成后的回调，初始化并注册服务。
        """
        logger.info("初始化 TTSVoicePlugin...")

        plugin_file = Path(__file__).resolve()
        bot_root = plugin_file.parent.parent.parent.parent.parent
        config_file = bot_root / "config" / "plugins" / self.plugin_name / self.config_file_name
        self._create_default_config(config_file)

        # 实例化 TTSService，并传入 get_config 方法
        self.tts_service = TTSService(self._get_config_wrapper)

        # 注册服务
        register_service("tts", self.tts_service)
        logger.info("TTSService 已成功初始化并注册。")

    def get_plugin_components(self) -> list[tuple[ComponentInfo, type]]:
        """
        返回插件包含的组件列表。
        """
        components = []
        if self.get_config("components.action_enabled", True):
            components.append((TTSVoiceAction.get_action_info(), TTSVoiceAction))
        if self.get_config("components.command_enabled", True):
            components.append((TTSVoiceCommand.get_plus_command_info(), TTSVoiceCommand))
        return components
