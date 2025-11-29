"""
多情感 TTS 核心服务

基于 GPT-SoVITS 的语音合成服务，支持：
- 多种情感风格
- 自动情感分析
- 音频后处理
"""

import asyncio
import base64
import io
import os
import re
from collections.abc import Callable
from typing import Any

import aiohttp
import soundfile as sf
from pedalboard import Convolution, Pedalboard, Reverb
from pedalboard.io import AudioFile

from src.common.logger import get_logger
from .emotion_analyzer import EmotionAnalyzer

logger = get_logger("gpt_sovits_emotion_tts.service")


class EmotionTTSService:
    """多情感 TTS 服务"""

    def __init__(self, get_config_func: Callable[[str, Any], Any], emotion_analyzer: EmotionAnalyzer):
        self.get_config = get_config_func
        self.emotion_analyzer = emotion_analyzer
        self.emotion_styles: dict[str, dict[str, Any]] = {}
        self.timeout: int = 180
        self.max_text_length: int = 1000
        self._load_config()

    def _load_config(self) -> None:
        """加载插件配置"""
        try:
            self.timeout = self.get_config("tts.timeout", 180)
            self.max_text_length = self.get_config("tts.max_text_length", 1000)
            self.emotion_styles = self._load_emotion_styles()

            if self.emotion_styles:
                logger.info(f"TTS服务已成功加载情感风格: {list(self.emotion_styles.keys())}")
            else:
                logger.warning("情感风格配置为空，请检查配置文件")
        except Exception as e:
            logger.error(f"TTS服务配置加载失败: {e}")

    def _load_emotion_styles(self) -> dict[str, dict[str, Any]]:
        """加载情感风格配置"""
        styles = {}
        global_server = self.get_config("tts.server", "http://127.0.0.1:9880")
        emotion_styles_config = self.get_config("emotion_styles", [])

        if not isinstance(emotion_styles_config, list):
            logger.error(f"emotion_styles 配置不是一个列表，而是 {type(emotion_styles_config)}")
            return styles

        # 查找默认配置（neutral）
        neutral_cfg = next((s for s in emotion_styles_config if s.get("emotion_name") == "neutral"), None)
        if not neutral_cfg:
            logger.warning("未找到 'neutral' 情感配置，将使用第一个配置作为默认。")
            if emotion_styles_config:
                neutral_cfg = emotion_styles_config[0]
            else:
                logger.error("没有任何情感风格配置！")
                return styles

        default_refer_wav = neutral_cfg.get("refer_wav_path", "")
        default_prompt_text = neutral_cfg.get("prompt_text", "")
        default_gpt_weights = neutral_cfg.get("gpt_weights", "")
        default_sovits_weights = neutral_cfg.get("sovits_weights", "")

        for style_cfg in emotion_styles_config:
            if not isinstance(style_cfg, dict):
                continue

            emotion_name = style_cfg.get("emotion_name")
            if not emotion_name:
                continue

            styles[emotion_name] = {
                "url": global_server,
                "display_name": style_cfg.get("display_name", emotion_name),
                "keywords": style_cfg.get("keywords", []),
                "refer_wav_path": style_cfg.get("refer_wav_path") or default_refer_wav,
                "prompt_text": style_cfg.get("prompt_text") or default_prompt_text,
                "prompt_language": style_cfg.get("prompt_language", "zh"),
                "gpt_weights": style_cfg.get("gpt_weights") or default_gpt_weights,
                "sovits_weights": style_cfg.get("sovits_weights") or default_sovits_weights,
                "speed_factor": style_cfg.get("speed_factor", 1.0),
                "text_language": style_cfg.get("text_language", "auto"),
            }
        return styles

    def get_available_emotions(self) -> list[str]:
        """获取所有可用的情感列表"""
        return list(self.emotion_styles.keys())

    def get_emotion_display_info(self) -> list[dict[str, str]]:
        """获取情感显示信息"""
        return [
            {
                "name": name,
                "display_name": style.get("display_name", name),
                "keywords": ", ".join(style.get("keywords", []))
            }
            for name, style in self.emotion_styles.items()
        ]

    def _determine_final_language(self, text: str, mode: str) -> str:
        """根据配置的语言策略和文本内容，决定最终发送给API的语言代码"""
        if mode not in ["auto", "auto_yue"]:
            return mode

        # 粤语检测
        if mode == "auto_yue":
            cantonese_keywords = ["嘅", "喺", "咗", "唔", "係", "啲", "咩", "乜", "喂"]
            if any(keyword in text for keyword in cantonese_keywords):
                logger.info("检测到粤语关键词，最终语言: yue")
                return "yue"

        # 日语检测
        japanese_chars = len(re.findall(r"[\u3040-\u309f\u30a0-\u30ff]", text))
        if japanese_chars > 5 and japanese_chars > len(re.findall(r"[\u4e00-\u9fff]", text)) * 0.5:
            logger.info("检测到日语字符，最终语言: ja")
            return "ja"

        logger.info(f"在 {mode} 模式下默认回退到: zh")
        return "zh"

    def _clean_text_for_tts(self, text: str) -> str:
        """清理文本以适合 TTS 合成"""
        # 1. 移除括号内容（动作描述等）
        text = re.sub(r"[\(（\[【].*?[\)）\]】]", "", text)
        # 2. 规范化标点
        text = re.sub(r"([，。！？、；：,.!?;:~\-`])\1+", r"\1", text)
        text = re.sub(r"~{2,}|～{2,}", "，", text)
        text = re.sub(r"\.{3,}|…{1,}", "。", text)

        # 3. 词语替换
        replacements = {"www": "哈哈哈", "hhh": "哈哈", "233": "哈哈", "666": "厉害", "88": "拜拜"}
        for old, new in replacements.items():
            text = text.replace(old, new)

        # 4. 移除特殊字符
        text = re.sub(r"[^\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ffa-zA-Z0-9\s，。！？、；：,.!?;:~～]", "", text)

        # 5. 确保结尾有标点
        if text and not text.endswith(tuple("，。！？、；：,.!?;:")):
            text += "。"

        # 6. 智能截断
        if len(text) > self.max_text_length:
            cut_text = text[:self.max_text_length]
            punctuation = "。！？.…"
            last_punc_pos = max(cut_text.rfind(p) for p in punctuation)

            if last_punc_pos != -1:
                text = cut_text[:last_punc_pos + 1]
            else:
                last_comma_pos = max(cut_text.rfind(p) for p in "，、；,;")
                if last_comma_pos != -1:
                    text = cut_text[:last_comma_pos + 1]
                else:
                    text = cut_text

        return text.strip()

    async def _switch_model_weights(self, base_url: str, weights_path: str | None, weight_type: str) -> bool:
        """切换模型权重"""
        if not weights_path:
            return True
            
        api_endpoint = f"/set_{weight_type}_weights"
        switch_url = f"{base_url}{api_endpoint}"
        
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                async with session.get(switch_url, params={"weights_path": weights_path}) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"切换 {weight_type} 模型失败: {resp.status} - {error_text}")
                        return False
                    else:
                        logger.info(f"成功切换 {weight_type} 模型为: {weights_path}")
                        return True
        except Exception as e:
            logger.error(f"请求切换 {weight_type} 模型时发生网络异常: {e}")
            return False

    async def _call_tts_api(
        self,
        style_config: dict,
        text: str,
        text_language: str,
        **kwargs
    ) -> bytes | None:
        """调用 TTS API"""
        ref_wav_path = kwargs.get("refer_wav_path")
        if not ref_wav_path:
            logger.error("API 调用失败：缺少 refer_wav_path")
            return None
            
        try:
            base_url = style_config["url"].rstrip("/")

            # 切换模型
            await self._switch_model_weights(base_url, kwargs.get("gpt_weights"), "gpt")
            await self._switch_model_weights(base_url, kwargs.get("sovits_weights"), "sovits")

            # 构建请求数据
            data = {
                "text": text,
                "text_lang": text_language,
                "ref_audio_path": ref_wav_path,
                "prompt_text": kwargs.get("prompt_text", ""),
                "prompt_lang": kwargs.get("prompt_language", "zh"),
            }

            # 合并高级配置
            advanced_config = self.get_config("tts_advanced", {})
            if isinstance(advanced_config, dict):
                data.update({k: v for k, v in advanced_config.items() if v is not None})

            # 设置语速
            if style_config.get("speed_factor") is not None:
                data["speed_factor"] = style_config["speed_factor"]

            tts_url = base_url if base_url.endswith("/tts") else f"{base_url}/tts"
            logger.info(f"发送到 TTS API 的数据: {data}")

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    tts_url,
                    json=data,
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as response:
                    if response.status == 200:
                        return await response.read()
                    else:
                        error_info = await response.text()
                        logger.error(f"TTS API调用失败: {response.status} - {error_info}")
                        return None
                        
        except asyncio.TimeoutError:
            logger.error("TTS服务请求超时")
            return None
        except Exception as e:
            logger.error(f"TTS API调用异常: {e}")
            return None

    async def _apply_spatial_effects(self, audio_data: bytes) -> bytes | None:
        """应用空间音效"""
        try:
            effects_config = self.get_config("spatial_effects", {})
            if not effects_config.get("enabled", False):
                return audio_data

            # 获取 IR 文件路径
            plugin_file = os.path.abspath(__file__)
            bot_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(plugin_file))))
            ir_path = os.path.join(bot_root, "assets", "small_room_ir.wav")

            effects = []

            # 混响效果
            if effects_config.get("reverb_enabled", False):
                effects.append(Reverb(
                    room_size=effects_config.get("room_size", 0.15),
                    damping=effects_config.get("damping", 0.5),
                    wet_level=effects_config.get("wet_level", 0.33),
                    dry_level=effects_config.get("dry_level", 0.4),
                    width=effects_config.get("width", 1.0)
                ))

            # 卷积混响
            if effects_config.get("convolution_enabled", False) and os.path.exists(ir_path):
                effects.append(Convolution(
                    impulse_response_filename=ir_path,
                    mix=effects_config.get("convolution_mix", 0.5)
                ))

            if not effects:
                return audio_data

            # 处理音频
            with io.BytesIO(audio_data) as audio_stream:
                with AudioFile(audio_stream, "r") as f:
                    board = Pedalboard(effects)
                    effected = board(f.read(f.frames), f.samplerate)

            with io.BytesIO() as output_stream:
                sf.write(output_stream, effected.T, f.samplerate, format="WAV")
                processed_audio_data = output_stream.getvalue()

            logger.info("成功应用空间效果。")
            return processed_audio_data

        except Exception as e:
            logger.error(f"应用空间效果时出错: {e}")
            return audio_data

    async def generate_voice(
        self,
        text: str,
        emotion_hint: str | None = None,
        chat_id: str | None = None,
        language_hint: str | None = None,
        auto_analyze: bool = True
    ) -> tuple[str | None, str]:
        """
        生成带情感的语音
        
        Args:
            text: 要合成的文本
            emotion_hint: 指定的情感（可选）
            chat_id: 聊天 ID（用于获取机器人情绪）
            language_hint: 语言提示
            auto_analyze: 是否自动分析情感
            
        Returns:
            (base64编码的音频数据, 使用的情感名称)
        """
        self._load_config()

        if not self.emotion_styles:
            logger.error("情感风格配置为空，无法生成语音。")
            return None, "neutral"

        # 确定使用的情感
        available_emotions = list(self.emotion_styles.keys())
        
        if emotion_hint and emotion_hint in self.emotion_styles:
            emotion = emotion_hint
            logger.info(f"使用指定情感: {emotion}")
        elif auto_analyze:
            emotion, confidence = await self.emotion_analyzer.analyze_emotion(
                text=text,
                chat_id=chat_id,
                available_emotions=available_emotions,
                use_llm=False  # 默认不使用 LLM，可以通过配置开启
            )
            logger.info(f"自动分析情感: {emotion} (置信度: {confidence})")
        else:
            emotion = "neutral"
            logger.info("使用默认情感: neutral")

        # 确保情感存在
        if emotion not in self.emotion_styles:
            emotion = "neutral" if "neutral" in self.emotion_styles else available_emotions[0]
            logger.warning(f"指定情感不存在，回退到: {emotion}")

        style_config = self.emotion_styles[emotion]
        
        # 清理文本
        clean_text = self._clean_text_for_tts(text)
        if not clean_text:
            logger.warning("清理后的文本为空")
            return None, emotion

        # 确定语言
        if language_hint:
            final_language = language_hint
        else:
            language_policy = style_config.get("text_language", "auto")
            final_language = self._determine_final_language(clean_text, language_policy)

        logger.info(f"开始TTS语音合成，文本：{clean_text[:50]}..., 情感：{emotion}, 语言: {final_language}")

        # 调用 TTS API
        audio_data = await self._call_tts_api(
            style_config=style_config,
            text=clean_text,
            text_language=final_language,
            refer_wav_path=style_config.get("refer_wav_path"),
            prompt_text=style_config.get("prompt_text"),
            prompt_language=style_config.get("prompt_language"),
            gpt_weights=style_config.get("gpt_weights"),
            sovits_weights=style_config.get("sovits_weights"),
        )

        if audio_data:
            # 应用空间效果
            spatial_config = self.get_config("spatial_effects", {})
            if spatial_config.get("enabled", False):
                logger.info("应用空间音频效果...")
                processed_audio = await self._apply_spatial_effects(audio_data)
                if processed_audio:
                    audio_data = processed_audio

            return base64.b64encode(audio_data).decode("utf-8"), emotion
        
        return None, emotion
