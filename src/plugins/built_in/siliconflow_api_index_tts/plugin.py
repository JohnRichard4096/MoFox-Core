"""
SiliconFlow IndexTTS 语音合成插件
基于SiliconFlow API的IndexTTS语音合成插件，支持高质量的零样本语音克隆和情感控制
"""

import os
import base64
import hashlib
import asyncio
import aiohttp
import json
import toml
from typing import Tuple, Optional, Dict, Any, List, Type
from pathlib import Path

from src.plugin_system import BasePlugin, BaseAction, BaseCommand, register_plugin, ConfigField
from src.plugin_system.base.base_action import ActionActivationType, ChatMode
from src.common.logger import get_logger

logger = get_logger("SiliconFlow-TTS")


def get_global_siliconflow_api_key() -> Optional[str]:
    """从全局配置文件中获取SiliconFlow API密钥"""
    try:
        # 读取全局model_config.toml配置文件
        config_path = Path("config/model_config.toml")
        if not config_path.exists():
            logger.error("全局配置文件 config/model_config.toml 不存在")
            return None
            
        with open(config_path, "r", encoding="utf-8") as f:
            model_config = toml.load(f)
            
        # 查找SiliconFlow API提供商配置
        api_providers = model_config.get("api_providers", [])
        for provider in api_providers:
            if provider.get("name") == "SiliconFlow":
                api_key = provider.get("api_key", "")
                if api_key:
                    logger.info("成功从全局配置读取SiliconFlow API密钥")
                    return api_key
                    
        logger.warning("在全局配置中未找到SiliconFlow API提供商或API密钥为空")
        return None
        
    except Exception as e:
        logger.error(f"读取全局配置失败: {e}")
        return None


class SiliconFlowTTSClient:
    """SiliconFlow TTS API客户端"""
    
    def __init__(self, api_key: str, base_url: str = "https://api.siliconflow.cn/v1/audio/speech", 
                 timeout: int = 60, max_retries: int = 3):
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries
        
    async def synthesize_speech(self, text: str, voice_id: str,
                               model: str = "IndexTeam/IndexTTS-2", 
                               speed: float = 1.0, volume: float = 1.0,
                               emotion_strength: float = 1.0,
                               output_format: str = "wav") -> bytes:
        """
        调用SiliconFlow API进行语音合成
        
        Args:
            text: 要合成的文本
            voice_id: 预配置的语音ID
            model: 模型名称 (默认使用IndexTeam/IndexTTS-2)
            speed: 语速
            volume: 音量
            emotion_strength: 情感强度
            output_format: 输出格式
            
        Returns:
            合成的音频数据
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # 构建请求数据
        data = {
            "model": model,
            "input": text,
            "voice": voice_id,
            "format": output_format,
            "speed": speed
        }
        
        logger.info(f"使用配置的Voice ID: {voice_id}")
        
        # 发送请求
        for attempt in range(self.max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        self.base_url,
                        headers=headers,
                        json=data,
                        timeout=aiohttp.ClientTimeout(total=self.timeout)
                    ) as response:
                        if response.status == 200:
                            audio_data = await response.read()
                            logger.info(f"语音合成成功，音频大小: {len(audio_data)} bytes")
                            return audio_data
                        else:
                            error_text = await response.text()
                            logger.error(f"API请求失败 (状态码: {response.status}): {error_text}")
                            if attempt == self.max_retries - 1:
                                raise Exception(f"API请求失败: {response.status} - {error_text}")
            except asyncio.TimeoutError:
                logger.warning(f"请求超时，尝试第 {attempt + 1}/{self.max_retries} 次")
                if attempt == self.max_retries - 1:
                    raise Exception("请求超时")
            except Exception as e:
                logger.error(f"请求异常: {e}")
                if attempt == self.max_retries - 1:
                    raise e
                await asyncio.sleep(2 ** attempt)  # 指数退避
        
        raise Exception("所有重试都失败了")


class SiliconFlowIndexTTSAction(BaseAction):
    """SiliconFlow IndexTTS Action组件"""

    # 激活设置
    focus_activation_type = ActionActivationType.LLM_JUDGE
    normal_activation_type = ActionActivationType.KEYWORD
    mode_enable = ChatMode.ALL
    parallel_action = False

    # 动作基本信息
    action_name = "siliconflow_indextts_action"
    action_description = "使用SiliconFlow API进行高质量的IndexTTS语音合成，支持零样本语音克隆"

    # 关键词配置
    activation_keywords = ["克隆语音", "模仿声音", "语音合成", "indextts", "声音克隆", "语音生成", "仿声", "变声"]
    keyword_case_sensitive = False

    # 动作参数定义
    action_parameters = {
        "text": "需要合成语音的文本内容，必填，应当清晰流畅",
        "speed": "语速（可选），范围0.1-3.0，默认1.0"
    }

    # 动作使用场景
    action_require = [
        "当用户要求语音克隆或模仿某个声音时使用",
        "当用户明确要求进行语音合成时使用",
        "当需要高质量语音输出时使用",
        "当用户要求变声或仿声时使用"
    ]

    # 关联类型 - 支持语音消息
    associated_types = ["voice"]

    async def execute(self) -> Tuple[bool, str]:
        """执行SiliconFlow IndexTTS语音合成"""
        logger.info(f"{self.log_prefix} 执行SiliconFlow IndexTTS动作: {self.reasoning}")

        # 优先从全局配置获取SiliconFlow API密钥
        api_key = get_global_siliconflow_api_key()
        if not api_key:
            # 如果全局配置中没有，则从插件配置获取（兼容旧版本）
            api_key = self.get_config("api.api_key", "")
            if not api_key:
                logger.error(f"{self.log_prefix} SiliconFlow API密钥未配置")
                return False, "请在全局配置 config/model_config.toml 中配置SiliconFlow API密钥"

        # 获取文本内容 - 多种来源尝试
        text = ""
        
        # 1. 尝试从action_data获取text参数
        text = self.action_data.get("text", "")
        if not text:
            # 2. 尝试从action_data获取tts_text参数（兼容其他TTS插件）
            text = self.action_data.get("tts_text", "")
        
        if not text:
            # 3. 如果没有提供具体文本，则生成一个基于reasoning的语音回复
            if self.reasoning:
                # 基于内心思考生成适合语音播报的内容
                # 这里可以进行一些处理，让内心思考更适合作为语音输出
                if "阿范" in self.reasoning and any(word in self.reasoning for word in ["想听", "语音", "声音"]):
                    # 如果reasoning表明用户想听语音，生成相应回复
                    text = "喵~阿范想听我的声音吗？那就用这个新的语音合成功能试试看吧~"
                elif "测试" in self.reasoning:
                    text = "好吧，那就试试这个新的语音合成功能吧~"
                else:
                    # 使用reasoning的内容，但做适当调整
                    text = self.reasoning
                logger.info(f"{self.log_prefix} 基于reasoning生成语音内容")
            else:
                # 如果完全没有内容，使用默认回复
                text = "喵~使用SiliconFlow IndexTTS测试语音合成功能~"
                logger.info(f"{self.log_prefix} 使用默认语音内容")
        
        # 获取其他参数
        speed = float(self.action_data.get("speed", self.get_config("synthesis.speed", 1.0)))

        try:
            # 获取预配置的voice_id
            voice_id = self.get_config("synthesis.voice_id", "")
            if not voice_id or not isinstance(voice_id, str):
                logger.error(f"{self.log_prefix} 配置中未找到有效的voice_id，请先运行upload_voice.py工具上传参考音频")
                return False, "配置中未找到有效的voice_id"

            logger.info(f"{self.log_prefix} 使用预配置的voice_id: {voice_id}")

            # 创建TTS客户端
            client = SiliconFlowTTSClient(
                api_key=api_key,
                base_url=self.get_config("api.base_url", "https://api.siliconflow.cn/v1/audio/speech"),
                timeout=self.get_config("api.timeout", 60),
                max_retries=self.get_config("api.max_retries", 3)
            )

            # 合成语音
            audio_data = await client.synthesize_speech(
                text=text,
                voice_id=voice_id,
                model=self.get_config("synthesis.model", "IndexTeam/IndexTTS-2"),
                speed=speed,
                output_format=self.get_config("synthesis.output_format", "wav")
            )

            # 转换为base64编码（语音消息需要base64格式）
            audio_base64 = base64.b64encode(audio_data).decode('utf-8')

            # 发送语音消息（使用voice类型，支持WAV格式的base64）
            await self.send_custom(
                message_type="voice", 
                content=audio_base64
            )

            # 记录动作信息
            await self.store_action_info(
                action_build_into_prompt=True, 
                action_prompt_display=f"已使用SiliconFlow IndexTTS生成语音: {text[:20]}...", 
                action_done=True
            )

            logger.info(f"{self.log_prefix} 语音合成成功，文本长度: {len(text)}")
            return True, "SiliconFlow IndexTTS语音合成成功"

        except Exception as e:
            logger.error(f"{self.log_prefix} 语音合成失败: {e}")
            return False, f"语音合成失败: {str(e)}"


class SiliconFlowTTSCommand(BaseCommand):
    """SiliconFlow TTS命令组件"""

    command_name = "sf_tts"
    command_description = "使用SiliconFlow IndexTTS进行语音合成"
    command_aliases = ["sftts", "sf语音", "硅基语音"]

    command_parameters = {
        "text": {"type": str, "required": True, "description": "要合成的文本"},
        "speed": {"type": float, "required": False, "description": "语速 (0.1-3.0)"}
    }

    async def execute(self, text: str, speed: float = 1.0) -> Tuple[bool, str]:
        """执行TTS命令"""
        logger.info(f"{self.log_prefix} 执行SiliconFlow TTS命令")

        # 优先从全局配置获取SiliconFlow API密钥
        api_key = get_global_siliconflow_api_key()
        if not api_key:
            # 如果全局配置中没有，则从插件配置获取（兼容旧版本）
            plugin = self.get_plugin()
            api_key = plugin.get_config("api.api_key", "")
            if not api_key:
                await self.send_reply("❌ SiliconFlow API密钥未配置！请在全局配置 config/model_config.toml 中设置。")
                return False, "API密钥未配置"

        try:
            await self.send_reply("正在使用SiliconFlow IndexTTS合成语音，请稍候...")

            # 使用默认参考音频 refer.mp3
            # 通过插件文件所在目录获取audio_reference目录
            plugin_dir = Path(__file__).parent
            audio_dir = plugin_dir / "audio_reference"
            reference_audio_path = audio_dir / "refer.mp3"
            
            if not reference_audio_path.exists():
                logger.warning(f"参考音频文件不存在: {reference_audio_path}")
                reference_audio_path = None

            # 创建TTS客户端
            client = SiliconFlowTTSClient(
                api_key=api_key,
                base_url="https://api.siliconflow.cn/v1/audio/speech",
                timeout=60,
                max_retries=3
            )

            # 合成语音
            audio_data = await client.synthesize_speech(
                text=text,
                reference_audio_path=str(reference_audio_path) if reference_audio_path else None,
                model="IndexTeam/IndexTTS-2",
                speed=speed,
                output_format="wav"
            )

            # 生成临时文件名
            text_hash = hashlib.md5(text.encode()).hexdigest()[:8]
            filename = f"siliconflow_tts_{text_hash}.wav"

            # 发送音频
            await self.send_custom(
                message_type="audio_file", 
                content=audio_data,
                filename=filename
            )

            await self.send_reply("✅ 语音合成完成！")
            return True, "命令执行成功"

        except Exception as e:
            error_msg = f"❌ 语音合成失败: {str(e)}"
            await self.send_reply(error_msg)
            logger.error(f"{self.log_prefix} 命令执行失败: {e}")
            return False, str(e)


@register_plugin
class SiliconFlowIndexTTSPlugin(BasePlugin):
    """SiliconFlow IndexTTS插件主类"""

    plugin_name = "siliconflow_api_index_tts"
    plugin_description = "基于SiliconFlow API的IndexTTS语音合成插件"
    plugin_version = "2.0.0"
    plugin_author = "MoFox Studio"

    # 必需的抽象属性
    enable_plugin: bool = True
    dependencies: list[str] = []
    config_file_name: str = "config.toml"

    # Python依赖
    python_dependencies = ["aiohttp>=3.8.0"]

    # 配置描述
    config_section_descriptions = {
        "plugin": "插件基本配置",
        "components": "组件启用配置", 
        "api": "SiliconFlow API配置",
        "synthesis": "语音合成配置"
    }

    # 配置schema
    config_schema = {
        "plugin": {
            "enabled": ConfigField(type=bool, default=False, description="是否启用插件"),
            "config_version": ConfigField(type=str, default="2.0.0", description="配置文件版本"),
        },
        "components": {
            "enable_action": ConfigField(type=bool, default=True, description="是否启用Action组件"),
            "enable_command": ConfigField(type=bool, default=True, description="是否启用Command组件"),
        },
        "api": {
            "api_key": ConfigField(type=str, default="", 
                                  description="SiliconFlow API密钥（可选，优先使用全局配置）"),
            "base_url": ConfigField(type=str, default="https://api.siliconflow.cn/v1/audio/speech", 
                                   description="SiliconFlow TTS API地址"),
            "timeout": ConfigField(type=int, default=60, description="API请求超时时间（秒）"),
            "max_retries": ConfigField(type=int, default=3, description="API请求最大重试次数"),
        },
        "synthesis": {
            "model": ConfigField(type=str, default="IndexTeam/IndexTTS-2", 
                                description="TTS模型名称"),
            "speed": ConfigField(type=float, default=1.0, 
                               description="默认语速 (0.1-3.0)"),
            "output_format": ConfigField(type=str, default="wav", 
                                       description="输出音频格式"),
        }
    }

    def get_plugin_components(self):
        """获取插件组件"""
        from src.plugin_system.base.component_types import ActionInfo, CommandInfo, ComponentType
        
        components = []
        
        # 检查配置是否启用组件
        if self.get_config("components.enable_action", True):
            action_info = ActionInfo(
                name="siliconflow_indextts_action",
                component_type=ComponentType.ACTION,
                description="使用SiliconFlow API进行高质量的IndexTTS语音合成",
                activation_keywords=["克隆语音", "模仿声音", "语音合成", "indextts", "声音克隆", "语音生成", "仿声", "变声"],
                plugin_name=self.plugin_name
            )
            components.append((action_info, SiliconFlowIndexTTSAction))

        if self.get_config("components.enable_command", True):
            command_info = CommandInfo(
                name="sf_tts",
                component_type=ComponentType.COMMAND,
                description="使用SiliconFlow IndexTTS进行语音合成",
                plugin_name=self.plugin_name
            )
            components.append((command_info, SiliconFlowTTSCommand))

        return components

    async def on_plugin_load(self):
        """插件加载时的回调"""
        logger.info("SiliconFlow IndexTTS插件已加载")
        
        # 检查audio_reference目录
        audio_dir = Path(self.plugin_path) / "audio_reference"
        if not audio_dir.exists():
            audio_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"创建音频参考目录: {audio_dir}")

        # 检查参考音频文件
        refer_file = audio_dir / "refer.mp3"
        if not refer_file.exists():
            logger.warning(f"参考音频文件不存在: {refer_file}")
            logger.info("请确保将自定义参考音频文件命名为 refer.mp3 并放置在 audio_reference 目录中")

        # 检查API密钥配置（优先检查全局配置）
        api_key = get_global_siliconflow_api_key()
        if not api_key:
            # 检查插件配置（兼容旧版本）
            plugin_api_key = self.get_config("api.api_key", "")
            if not plugin_api_key:
                logger.warning("SiliconFlow API密钥未配置，请在全局配置 config/model_config.toml 中设置SiliconFlow API提供商")
            else:
                logger.info("检测到插件本地API密钥配置（建议迁移到全局配置）")
        else:
            logger.info("SiliconFlow API密钥配置检查通过")

        # 你怎么知道我终于丢掉了我自己的脑子并使用了ai来帮我写代码的
        # 我也不知道，反正我现在就这样干了（）

    async def on_plugin_unload(self):
        """插件卸载时的回调"""
        logger.info("SiliconFlow IndexTTS插件已卸载")