"""
TTS Voice 插件 - 重构版
"""
import base64
import io
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Dict, AsyncIterator

import toml
import numpy as np
import soundfile as sf
from openai import OpenAI

from src.common.logger import get_logger
from src.plugin_system import BasePlugin, ComponentInfo, register_plugin
from src.plugin_system.base.component_types import PermissionNodeField
from src.plugin_system.base.config_types import ConfigField

from .actions.tts_action import TTSVoiceAction
from .commands.tts_command import TTSVoiceCommand
from .services.manager import register_service
from .services.tts_service import TTSService

logger = get_logger("tts_voice_plugin")

@dataclass
class QwenOmniConfig:
    """Qwen Omni TTS 配置"""
    api_key: str
    model_name: str = "qwen-omni-turbo"
    voice_character: str = "Chelsie"
    media_format: str = "wav"
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QwenOmniConfig":
        return cls(
            api_key=data.get("api_key", ""),
            model_name=data.get("model_name", "qwen-omni-turbo"),
            voice_character=data.get("voice_character", "Chelsie"),
            media_format=data.get("media_format", "wav"),
            base_url=data.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        )


class QwenOmniTTSModel:
    """Qwen Omni TTS 模型"""
    
    def __init__(self, get_config_func):
        """初始化TTS模型
        
        Args:
            get_config_func: 插件配置获取函数
        """
        self.get_config = get_config_func
        self.config = self._load_config()

    def _load_config(self) -> QwenOmniConfig:
        """从插件配置加载Qwen Omni配置"""
        try:
            config_data = {
                "api_key": self.get_config("qwen_omni.api_key", ""),
                "model_name": self.get_config("qwen_omni.model_name", "qwen-omni-turbo"),
                "voice_character": self.get_config("qwen_omni.voice_character", "Chelsie"),
                "media_format": self.get_config("qwen_omni.media_format", "wav"),
                "base_url": self.get_config("qwen_omni.base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            }
            return QwenOmniConfig.from_dict(config_data)
        except Exception as e:
            logger.error(f"加载 Qwen Omni 配置失败: {e}")
            return QwenOmniConfig(api_key="")

    async def tts(self, text: str, **kwargs) -> bytes:
        """文本转语音 - 将PCM数据转换为WAV文件"""
        try:
            audio_base64_string = ""
            chunk_count = 0
            
            async for chunk in self._tts_stream(text, **kwargs):
                audio_base64_string += chunk
                chunk_count += 1
                
            if not audio_base64_string:
                logger.error("没有收到任何音频数据")
                return None
                
            # 解码base64得到PCM数据
            pcm_data = base64.b64decode(audio_base64_string)
            
            # 将PCM数据转换为WAV文件
            wav_bytes = self._pcm_to_wav_soundfile(pcm_data)
            
            return wav_bytes
        except Exception as e:
            logger.error(f"Qwen Omni TTS 失败: {e}")
            logger.error(traceback.format_exc())
            return None

    def _pcm_to_wav_soundfile(self, pcm_data: bytes, sample_rate: int = 24000, channels: int = 1) -> bytes:
        """使用soundfile将PCM数据转换为WAV文件"""
        try:
            import io
            import numpy as np
            
            # 将PCM字节数据转换为numpy数组
            # 假设是16位有符号整数（这是最常见的PCM格式）
            audio_array = np.frombuffer(pcm_data, dtype=np.int16)
            
            # 创建字节流
            wav_io = io.BytesIO()
            
            # 使用soundfile写入WAV格式
            sf.write(wav_io, audio_array, sample_rate, format='WAV')
            
            # 获取WAV文件数据
            wav_bytes = wav_io.getvalue()
            wav_io.close()
            
            logger.info(f"使用soundfile转换PCM到WAV: {len(pcm_data)}字节PCM -> {len(wav_bytes)}字节WAV")
            return wav_bytes
            
        except Exception as e:
            logger.error(f"使用soundfile转换PCM到WAV失败: {e}")
            logger.error(traceback.format_exc())
            return pcm_data
            
    async def _tts_stream(self, text: str, **kwargs) -> AsyncIterator[str]:
        """使用大模型流式生成音频数据"""
        try:
            logger.info(f"开始调用Qwen Omni API生成音频，文本: {text[:30]}{'...' if len(text) > 30 else ''}")
            
            prompt = f"复述这句话，不要输出其他内容，只输出'{text}'就好，不要输出其他内容，不要输出前后缀，不要输出'{text}'以外的内容，不要说：如果还有类似的需求或者想聊聊别的"
            logger.info(f"使用prompt: {prompt}")
            
            client = OpenAI(api_key=self.config.api_key, base_url=self.config.base_url)
            
            completion = client.chat.completions.create(
                model=self.config.model_name,
                messages=[{"role": "user", "content": prompt}],
                modalities=["text", "audio"],
                audio={
                    "voice": self.config.voice_character,
                    "format": self.config.media_format,
                },
                stream=True,
                stream_options={"include_usage": True},
            )
        
            audio_data_received = False
            total_audio_length = 0
            
            for chunk in completion:
                if hasattr(chunk, "choices") and chunk.choices:
                    delta = chunk.choices[0].delta
                
                    # 检查音频数据
                    if hasattr(delta, "audio") and delta.audio:
                        audio_dict = delta.audio
                        if isinstance(audio_dict, dict) and 'data' in audio_dict and audio_dict['data']:
                            audio_data = audio_dict['data']
                            total_audio_length += len(audio_data)
                            audio_data_received = True
                            yield audio_data
                        else:
                            logger.debug(f"音频字典内容: {audio_dict}")
                
                    # 记录文本内容用于调试
                    if hasattr(delta, "content") and delta.content:
                        logger.debug(f"收到文本内容: {delta.content}")
                        
                if hasattr(chunk, "usage") and chunk.usage:
                    logger.info(f"本次使用量: {chunk.usage}")
        
            logger.info(f"音频数据接收完成，总base64长度: {total_audio_length}")
            if not audio_data_received:
                logger.warning("API调用成功但没有收到音频数据")
                
        except Exception as e:
            logger.error(f"Qwen Omni API调用失败: {e}")
            logger.error(traceback.format_exc())
            raise

    async def generate_voice(self, text: str, style_hint: str = "default", language_hint: str | None = None) -> str | None:
        """生成语音的兼容接口"""
        try:
            logger.info(f"开始生成语音，文本: {text}")
            audio_data = await self.tts(text)
            if audio_data:
                logger.info(f"语音生成成功，数据长度: {len(audio_data)} 字节")
                # 直接返回base64编码的WAV数据
                return base64.b64encode(audio_data).decode("utf-8")
            else:
                logger.error("语音生成失败，audio_data 为 None")
                return None
        except Exception as e:
            logger.error(f"Qwen Omni 语音生成失败: {e}")
            logger.error(traceback.format_exc())
            return None


@register_plugin
class TTSVoicePlugin(BasePlugin):
    """
    GPT-SoVITS 和 Qwen Omni 语音合成插件
    """

    plugin_name = "tts_voice_plugin"
    plugin_description = "基于GPT-SoVITS和Qwen Omni的文本转语音插件"
    plugin_version = "3.2.0"
    plugin_author = "Kilo Code & 靓仔 & AI助手"
    config_file_name = "config.toml"
    dependencies: ClassVar[list[str]] = []

    permission_nodes: ClassVar[list[PermissionNodeField]] = [
        PermissionNodeField(node_name="command.use", description="是否可以使用 /tts 命令"),
    ]

    # 使用 ConfigField 的配置架构
    config_schema: ClassVar[dict] = {
        "plugin": {
            "enabled": ConfigField(type=bool, default=True, description="是否启用插件"),
            "debug": ConfigField(type=bool, default=False, description="是否开启调试模式")
        },
        "components": {
            "action_enabled": ConfigField(type=bool, default=True, description="是否启用TTS Action"),
            "command_enabled": ConfigField(type=bool, default=True, description="是否启用TTS命令")
        },
        "tts": {
            "server": ConfigField(type=str, default="http://127.0.0.1:9880", description="GPT-SoVITS服务器地址"),
            "timeout": ConfigField(type=int, default=60, description="TTS请求超时时间（秒）"),
            "max_text_length": ConfigField(type=int, default=500, description="最大文本长度"),
            "engine": ConfigField(
                type=str, 
                default="gpt-sovits", 
                description="TTS引擎选择", 
                choices=["gpt-sovits", "qwen-omni"]
            )
        },
        "qwen_omni": {
            "api_key": ConfigField(type=str, default="", description="Qwen Omni API密钥", required=True),
            "base_url": ConfigField(
                type=str, 
                default="https://dashscope.aliyuncs.com/compatible-mode/v1", 
                description="Qwen Omni API基础URL"
            ),
            "model_name": ConfigField(type=str, default="qwen-omni-turbo", description="Qwen Omni模型名称"),
            "voice_character": ConfigField(type=str, default="Chelsie", description="语音角色"),
            "media_format": ConfigField(type=str, default="wav", description="音频格式")
        },
        "tts_advanced": {
            "top_k": ConfigField(type=int, default=5, description="Top-K采样参数"),
            "top_p": ConfigField(type=float, default=1.0, description="Top-P采样参数"),
            "temperature": ConfigField(type=float, default=1.0, description="温度参数"),
            "batch_size": ConfigField(type=int, default=1, description="批处理大小"),
            "split_bucket": ConfigField(type=bool, default=True, description="是否启用分桶处理")
        },
        "spatial_effects": {
            "enabled": ConfigField(type=bool, default=False, description="是否启用空间音效"),
            "reverb_enabled": ConfigField(type=bool, default=True, description="是否启用混响效果"),
            "room_size": ConfigField(type=float, default=0.15, description="混响房间大小"),
            "damping": ConfigField(type=float, default=0.5, description="混响阻尼"),
            "wet_level": ConfigField(type=float, default=0.33, description="湿声比例"),
            "dry_level": ConfigField(type=float, default=0.4, description="干声比例"),
            "width": ConfigField(type=float, default=1.0, description="立体声宽度"),
            "convolution_enabled": ConfigField(type=bool, default=False, description="是否启用卷积混响"),
            "convolution_mix": ConfigField(type=float, default=0.5, description="卷积混响干湿比")
        }
    }

    config_section_descriptions: ClassVar[dict] = {
        "plugin": "插件基本配置",
        "components": "组件启用控制", 
        "tts": "TTS语音合成基础配置",
        "qwen_omni": "Qwen Omni大模型TTS配置（需要API Key）",
        "tts_advanced": "TTS高级参数配置",
        "spatial_effects": "空间音频效果配置"
    }

    def __init__(self, *args, **kwargs):
        try:
            logger.info("TTSVoicePlugin 初始化开始")
            super().__init__(*args, **kwargs)
            self.tts_service = None
            logger.info("TTSVoicePlugin 初始化完成")
        except Exception as e:
            logger.error(f"TTSVoicePlugin 初始化失败: {e}")
            logger.error(traceback.format_exc())
            raise

    async def on_plugin_loaded(self):
        """
        插件加载完成后的回调，初始化并注册服务。
        """
        try:
            logger.info("开始初始化 TTSVoicePlugin...")

            # 获取当前使用的TTS引擎
            engine = self.get_config("tts.engine", "gpt-sovits")
            logger.info(f"当前TTS引擎: {engine}")

            if engine == "gpt-sovits":
                # 实例化 GPT-SoVITS 服务
                logger.info("初始化 GPT-SoVITS 服务...")
                self.tts_service = TTSService(self.get_config)
                register_service("tts", self.tts_service)
                logger.info("GPT-SoVITS TTSService 已成功初始化并注册。")
            
            elif engine == "qwen-omni":
                # 检查API Key
                api_key = self.get_config("qwen_omni.api_key", "")
                if not api_key or api_key == "your-api-key-here":
                    logger.error("Qwen Omni 需要配置有效的 API Key，请在插件配置中设置 qwen_omni.api_key")
                    # 创建空服务，避免后续调用出错
                    self.tts_service = None
                else:
                    # 实例化 Qwen Omni 服务
                    logger.info("初始化 Qwen Omni 服务...")
                    self.tts_service = QwenOmniTTSModel(self.get_config)
                    register_service("tts", self.tts_service)
                    logger.info("Qwen Omni TTSModel 已成功初始化并注册。")
            else:
                logger.error(f"不支持的 TTS 引擎: {engine}")
                self.tts_service = None

            logger.info("TTSVoicePlugin 初始化完成")

        except Exception as e:
            logger.error(f"TTSVoicePlugin 初始化过程中发生错误: {e}")
            logger.error(traceback.format_exc())
            # 不要重新抛出异常，避免影响主程序

    def get_plugin_components(self) -> list[tuple[ComponentInfo, type]]:
        """
        返回插件包含的组件列表。
        """
        try:
            components = []
            if self.get_config("components.action_enabled", True):
                components.append((TTSVoiceAction.get_action_info(), TTSVoiceAction))
            if self.get_config("components.command_enabled", True):
                components.append((TTSVoiceCommand.get_plus_command_info(), TTSVoiceCommand))
            logger.info(f"加载了 {len(components)} 个组件")
            return components
        except Exception as e:
            logger.error(f"获取插件组件失败: {e}")
            logger.error(traceback.format_exc())
            return []