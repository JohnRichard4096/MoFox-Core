"""
MessageEnvelope 转换器

将 mofox_bus 的 MessageEnvelope 转换为 MoFox Bot 内部使用的消息格式。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from mofox_bus import MessageEnvelope, BaseMessageInfo, FormatInfo, GroupInfo, MessageBase, Seg, UserInfo

from src.common.logger import get_logger

logger = get_logger("envelope_converter")


class EnvelopeConverter:
    """MessageEnvelope 到内部消息格式的转换器"""

    @staticmethod
    def to_message_base(envelope: MessageEnvelope) -> MessageBase:
        """
        将 MessageEnvelope 转换为 MessageBase
        
        Args:
            envelope: 统一的消息信封
            
        Returns:
            MessageBase: 内部消息格式
        """
        try:
            # 提取基本信息
            platform = envelope["platform"]
            channel = envelope["channel"]
            sender = envelope["sender"]
            content = envelope["content"]
            
            # 创建 UserInfo
            user_info = UserInfo(
                user_id=sender["user_id"],
                user_nickname=sender.get("display_name", sender["user_id"]),
                user_avatar=sender.get("avatar_url"),
            )
            
            # 创建 GroupInfo (如果是群组消息)
            group_info: Optional[GroupInfo] = None
            if channel["channel_type"] in ("group", "supergroup", "room"):
                group_info = GroupInfo(
                    group_id=channel["channel_id"],
                    group_name=channel.get("title", channel["channel_id"]),
                )
            
            # 创建 BaseMessageInfo
            message_info = BaseMessageInfo(
                platform=platform,
                chat_type="group" if group_info else "private",
                message_id=envelope["id"],
                user_info=user_info,
                group_info=group_info,
                timestamp=envelope["timestamp_ms"] / 1000.0,  # 转换为秒
            )
            
            # 转换 Content 为 Seg 列表
            segments = EnvelopeConverter._content_to_segments(content)
            
            # 创建 MessageBase
            message_base = MessageBase(
                message_info=message_info,
                message=segments,
            )
            
            # 保存原始 envelope 到 raw 字段
            if hasattr(message_base, "raw"):
                message_base.raw = envelope
            
            return message_base
            
        except Exception as e:
            logger.error(f"转换 MessageEnvelope 失败: {e}", exc_info=True)
            raise

    @staticmethod
    def _content_to_segments(content: Dict[str, Any]) -> List[Seg]:
        """
        将 Content 转换为 Seg 列表
        
        Args:
            content: 消息内容
            
        Returns:
            List[Seg]: 消息段列表
        """
        segments: List[Seg] = []
        content_type = content.get("type")
        
        if content_type == "text":
            # 文本消息
            text = content.get("text", "")
            segments.append(Seg.text(text))
            
        elif content_type == "image":
            # 图片消息
            url = content.get("url", "")
            file_id = content.get("file_id")
            segments.append(Seg.image(url if url else file_id))
            
        elif content_type == "audio":
            # 音频消息
            url = content.get("url", "")
            file_id = content.get("file_id")
            segments.append(Seg.record(url if url else file_id))
            
        elif content_type == "video":
            # 视频消息
            url = content.get("url", "")
            file_id = content.get("file_id")
            segments.append(Seg.video(url if url else file_id))
            
        elif content_type == "file":
            # 文件消息
            url = content.get("url", "")
            file_name = content.get("file_name", "file")
            # 使用 text 表示文件（或者可以自定义一个 file seg type）
            segments.append(Seg.text(f"[文件: {file_name}]"))
            
        elif content_type == "command":
            # 命令消息
            name = content.get("name", "")
            args = content.get("args", {})
            # 重构为文本格式
            cmd_text = f"/{name}"
            if args:
                cmd_text += " " + " ".join(f"{k}={v}" for k, v in args.items())
            segments.append(Seg.text(cmd_text))
            
        elif content_type == "event":
            # 事件消息 - 转换为文本表示
            event_type = content.get("event_type", "unknown")
            segments.append(Seg.text(f"[事件: {event_type}]"))
            
        elif content_type == "system":
            # 系统消息
            text = content.get("text", "")
            segments.append(Seg.text(f"[系统] {text}"))
            
        else:
            # 未知类型 - 转换为文本
            logger.warning(f"未知的消息类型: {content_type}")
            segments.append(Seg.text(f"[未知消息类型: {content_type}]"))
        
        return segments

    @staticmethod
    def to_legacy_dict(envelope: MessageEnvelope) -> Dict[str, Any]:
        """
        将 MessageEnvelope 转换为旧版字典格式（用于向后兼容）
        
        Args:
            envelope: 统一的消息信封
            
        Returns:
            Dict[str, Any]: 旧版消息字典
        """
        message_base = EnvelopeConverter.to_message_base(envelope)
        return message_base.to_dict()

    @staticmethod
    def from_message_base(message: MessageBase, direction: str = "outgoing") -> MessageEnvelope:
        """
        将 MessageBase 转换为 MessageEnvelope (反向转换)
        
        Args:
            message: 内部消息格式
            direction: 消息方向 ("incoming" 或 "outgoing")
            
        Returns:
            MessageEnvelope: 统一的消息信封
        """
        try:
            message_info = message.message_info
            user_info = message_info.user_info
            group_info = message_info.group_info
            
            # 创建 SenderInfo
            sender = {
                "user_id": user_info.user_id,
                "role": "assistant" if direction == "outgoing" else "user",
            }
            if user_info.user_nickname:
                sender["display_name"] = user_info.user_nickname
            if user_info.user_avatar:
                sender["avatar_url"] = user_info.user_avatar
            
            # 创建 ChannelInfo
            if group_info:
                channel = {
                    "channel_id": group_info.group_id,
                    "channel_type": "group",
                }
                if group_info.group_name:
                    channel["title"] = group_info.group_name
            else:
                channel = {
                    "channel_id": user_info.user_id,
                    "channel_type": "private",
                }
            
            # 转换 segments 为 Content
            content = EnvelopeConverter._segments_to_content(message.message)
            
            # 创建 MessageEnvelope
            envelope: MessageEnvelope = {
                "id": message_info.message_id,
                "direction": direction,
                "platform": message_info.platform,
                "timestamp_ms": int(message_info.timestamp * 1000),
                "channel": channel,
                "sender": sender,
                "content": content,
                "conversation_id": group_info.group_id if group_info else user_info.user_id,
            }
            
            return envelope
            
        except Exception as e:
            logger.error(f"转换 MessageBase 失败: {e}", exc_info=True)
            raise

    @staticmethod
    def _segments_to_content(segments: List[Seg]) -> Dict[str, Any]:
        """
        将 Seg 列表转换为 Content
        
        Args:
            segments: 消息段列表
            
        Returns:
            Dict[str, Any]: 消息内容
        """
        if not segments:
            return {"type": "text", "text": ""}
        
        # 简化处理：如果有多个段，合并为文本
        if len(segments) == 1:
            seg = segments[0]
            
            if seg.type == "text":
                return {"type": "text", "text": seg.data.get("text", "")}
            elif seg.type == "image":
                return {"type": "image", "url": seg.data.get("file", "")}
            elif seg.type == "record":
                return {"type": "audio", "url": seg.data.get("file", "")}
            elif seg.type == "video":
                return {"type": "video", "url": seg.data.get("file", "")}
        
        # 多个段或未知类型 - 合并为文本
        text_parts = []
        for seg in segments:
            if seg.type == "text":
                text_parts.append(seg.data.get("text", ""))
            elif seg.type == "image":
                text_parts.append("[图片]")
            elif seg.type == "record":
                text_parts.append("[语音]")
            elif seg.type == "video":
                text_parts.append("[视频]")
            else:
                text_parts.append(f"[{seg.type}]")
        
        return {"type": "text", "text": "".join(text_parts)}


__all__ = ["EnvelopeConverter"]
