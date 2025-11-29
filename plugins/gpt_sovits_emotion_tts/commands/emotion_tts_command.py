"""
多情感 TTS 语音合成命令
"""
from typing import ClassVar

from src.common.logger import get_logger
from src.plugin_system.base.command_args import CommandArgs
from src.plugin_system.base.plus_command import PlusCommand
from src.plugin_system.utils.permission_decorators import require_permission

from ..services.service_manager import get_service

logger = get_logger("gpt_sovits_emotion_tts.command")


class EmotionTTSCommand(PlusCommand):
    """
    通过命令手动触发多情感 TTS 语音合成
    
    用法:
        /etts <文本>              - 自动分析情感
        /etts <文本> --emotion happy  - 指定情感
        /etts list               - 列出可用情感
    """

    command_name: str = "etts"
    command_description: str = "使用GPT-SoVITS将文本转换为带情感的语音并发送"
    command_aliases: ClassVar[list[str]] = ["情感语音", "emotion_tts"]
    command_usage = "/etts <要说的文本> [--emotion 情感名称]\n/etts list - 查看可用情感"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @require_permission("plugin.gpt_sovits_emotion_tts.command.use")
    async def execute(self, args: CommandArgs) -> tuple[bool, str | None, bool]:
        """
        执行命令的核心逻辑
        """
        all_args = args.get_args()
        
        if not all_args:
            await self.send_text(
                "📢 多情感语音合成命令\n\n"
                "用法:\n"
                "  /etts <文本> - 自动分析情感\n"
                "  /etts <文本> --emotion <情感> - 指定情感\n"
                "  /etts list - 查看可用情感\n\n"
                "示例:\n"
                "  /etts 今天天气真好啊\n"
                "  /etts 我好开心 --emotion happy"
            )
            return True, "显示帮助信息", True

        # 处理 list 命令
        if all_args[0].lower() == "list":
            return await self._handle_list_emotions()

        try:
            tts_service = get_service("emotion_tts")
            if not tts_service:
                raise RuntimeError("EmotionTTSService 未注册或初始化失败")

            # 解析参数
            text_parts = []
            emotion_hint = None
            i = 0
            
            while i < len(all_args):
                arg = all_args[i]
                if arg == "--emotion" and i + 1 < len(all_args):
                    emotion_hint = all_args[i + 1]
                    i += 2
                else:
                    text_parts.append(arg)
                    i += 1

            text_to_speak = " ".join(text_parts)
            
            if not text_to_speak:
                await self.send_text("请提供要转换为语音的文本内容！")
                return False, "文本内容为空", True

            # 验证情感
            available_emotions = tts_service.get_available_emotions()
            if emotion_hint and emotion_hint not in available_emotions:
                await self.send_text(
                    f"❌ 未知的情感: {emotion_hint}\n\n"
                    f"可用情感: {', '.join(available_emotions)}"
                )
                return False, "未知的情感", True

            # 生成语音
            audio_b64, used_emotion = await tts_service.generate_voice(
                text=text_to_speak,
                emotion_hint=emotion_hint,
                auto_analyze=True
            )

            if audio_b64:
                await self.send_type(message_type="voice", content=audio_b64)
                emotion_info = tts_service.emotion_styles.get(used_emotion, {})
                display_name = emotion_info.get("display_name", used_emotion)
                logger.info(f"语音发送成功，使用情感: {used_emotion} ({display_name})")
                return True, f"语音发送成功，情感: {display_name}", True
            else:
                await self.send_text("❌ 语音合成失败，请检查服务状态或配置。")
                return False, "语音合成失败", True

        except Exception as e:
            logger.error(f"执行 /etts 命令时出错: {e}")
            await self.send_text("❌ 语音合成时发生了意想不到的错误，请查看日志。")
            return False, "命令执行异常", True

    async def _handle_list_emotions(self) -> tuple[bool, str, bool]:
        """处理列出情感的命令"""
        try:
            tts_service = get_service("emotion_tts")
            if not tts_service:
                await self.send_text("❌ TTS 服务未初始化")
                return False, "服务未初始化", True

            emotion_info = tts_service.get_emotion_display_info()
            
            lines = ["🎭 可用的情感风格:\n"]
            for info in emotion_info:
                name = info["name"]
                display_name = info["display_name"]
                keywords = info.get("keywords", "")
                lines.append(f"  • {name} ({display_name})")
                if keywords:
                    lines.append(f"    关键词: {keywords}")
            
            lines.append("\n使用方法: /etts <文本> --emotion <情感名称>")
            
            await self.send_text("\n".join(lines))
            return True, "显示情感列表", True
            
        except Exception as e:
            logger.error(f"获取情感列表时出错: {e}")
            await self.send_text("❌ 获取情感列表失败")
            return False, "获取列表失败", True
