import asyncio
import re
import math
import traceback
from datetime import datetime

from typing import Tuple, TYPE_CHECKING

from src.config.config import global_config
from src.chat.memory_system.Hippocampus import hippocampus_manager
from src.chat.message_receive.message import MessageRecv
from src.chat.message_receive.storage import MessageStorage
from src.chat.heart_flow.heartflow import heartflow
from src.chat.utils.utils import is_mentioned_bot_in_message
from src.chat.utils.timer_calculator import Timer
from src.chat.utils.chat_message_builder import replace_user_references_sync
from src.common.logger import get_logger
from src.mood.mood_manager import mood_manager

if TYPE_CHECKING:
    from src.chat.heart_flow.sub_heartflow import SubHeartflow

logger = get_logger("chat")

async def _calculate_interest(message: MessageRecv) -> Tuple[float, bool, list[str]]:
    """计算消息的兴趣度

    Args:
        message: 待处理的消息对象

    Returns:
        Tuple[float, bool, list[str]]: (兴趣度, 是否被提及, 关键词)
    """
    is_mentioned, _ = is_mentioned_bot_in_message(message)
    interested_rate = 0.0

    with Timer("记忆激活"):
        interested_rate, keywords = await hippocampus_manager.get_activate_from_text(
            message.processed_plain_text,
            max_depth=4,
            fast_retrieval=False,
        )
        message.key_words = keywords
        message.key_words_lite = keywords
        logger.debug(f"记忆激活率: {interested_rate:.2f}, 关键词: {keywords}")

    text_len = len(message.processed_plain_text)
    # 根据文本长度分布调整兴趣度，采用分段函数实现更精确的兴趣度计算
    # 基于实际分布：0-5字符(26.57%), 6-10字符(27.18%), 11-20字符(22.76%), 21-30字符(10.33%), 31+字符(13.86%)

    if text_len == 0:
        base_interest = 0.01  # 空消息最低兴趣度
    elif text_len <= 5:
        # 1-5字符：线性增长 0.01 -> 0.03
        base_interest = 0.01 + (text_len - 1) * (0.03 - 0.01) / 4
    elif text_len <= 10:
        # 6-10字符：线性增长 0.03 -> 0.06
        base_interest = 0.03 + (text_len - 5) * (0.06 - 0.03) / 5
    elif text_len <= 20:
        # 11-20字符：线性增长 0.06 -> 0.12
        base_interest = 0.06 + (text_len - 10) * (0.12 - 0.06) / 10
    elif text_len <= 30:
        # 21-30字符：线性增长 0.12 -> 0.18
        base_interest = 0.12 + (text_len - 20) * (0.18 - 0.12) / 10
    elif text_len <= 50:
        # 31-50字符：线性增长 0.18 -> 0.22
        base_interest = 0.18 + (text_len - 30) * (0.22 - 0.18) / 20
    elif text_len <= 100:
        # 51-100字符：线性增长 0.22 -> 0.26
        base_interest = 0.22 + (text_len - 50) * (0.26 - 0.22) / 50
    else:
        # 100+字符：对数增长 0.26 -> 0.3，增长率递减
        base_interest = 0.26 + (0.3 - 0.26) * (math.log10(text_len - 99) / math.log10(901))  # 1000-99=901

    # 确保在范围内
    base_interest = min(max(base_interest, 0.01), 0.3)

    interested_rate += base_interest

    if is_mentioned:
        interest_increase_on_mention = 1
        interested_rate += interest_increase_on_mention

    return interested_rate, is_mentioned, keywords


class HeartFCMessageReceiver:
    """心流处理器，负责处理接收到的消息并计算兴趣度"""

    def __init__(self):
        """初始化心流处理器，创建消息存储实例"""
        self.storage = MessageStorage()

    async def process_message(self, message: MessageRecv) -> None:
        """处理接收到的原始消息数据

        主要流程:
        1. 消息解析与初始化
        2. 智能提醒分析
        3. 消息缓冲处理
        4. 过滤检查
        5. 兴趣度计算
        6. 关系处理

        Args:
            message_data: 原始消息字符串
        """
        try:
            # 1. 消息解析与初始化
            userinfo = message.message_info.user_info
            chat = message.chat_stream

            # 2. 智能提醒分析 - 检查用户是否请求提醒
            from src.chat.chat_loop.proactive.smart_reminder_analyzer import smart_reminder_analyzer
            from src.chat.chat_loop.proactive.event_scheduler import event_scheduler
            
            try:
                reminder_event = await smart_reminder_analyzer.analyze_message(
                    userinfo.user_id,  # type: ignore
                    message.processed_plain_text
                )
                if reminder_event:
                    logger.info(f"检测到提醒请求: {reminder_event}")
                    
                    # 创建提醒回调函数
                    async def reminder_callback(metadata):
                        """提醒执行回调函数 - 触发完整的主动思考流程"""
                        try:
                            # 获取对应的subheartflow实例
                            from src.chat.heart_flow.heartflow import heartflow
                            
                            subflow = await heartflow.get_or_create_subheartflow(metadata.get("chat_id"))
                            if not subflow:
                                logger.error(f"无法获取subheartflow实例: {metadata.get('chat_id')}")
                                return
                                
                            # 创建主动思考事件，触发完整的思考流程
                            from src.chat.chat_loop.proactive.events import ProactiveTriggerEvent
                            
                            reminder_content = metadata.get('content', '提醒时间到了')
                            # 使用原始消息内容作为reason，如果没有则使用处理后的内容
                            original_message = metadata.get('original_message', '')
                            reason_content = original_message if original_message else reminder_content
                            
                            event = ProactiveTriggerEvent(
                                source="reminder_system",
                                reason=f"定时提醒：{reason_content}",
                                metadata=metadata,
                                related_message_id=metadata.get("original_message_id")
                           )
                            
                            # 通过subflow的HeartFChatting实例触发主动思考
                            await subflow.heart_fc_instance.proactive_thinker.think(event)
                            
                            logger.info(f"已触发提醒的主动思考，内容: {reminder_content}")
                            
                        except Exception as callback_error:
                            logger.error(f"执行提醒回调失败: {callback_error}")
                            import traceback
                            logger.error(traceback.format_exc())
                            
                            # Fallback: 如果主动思考失败，直接发送提醒消息
                            try:
                                from src.plugin_system.apis.send_api import text_to_stream
                                reminder_content = metadata.get('content', '提醒时间到了')
                                await text_to_stream(
                                    text=f"⏰ 提醒：{reminder_content}",
                                    stream_id=metadata.get("chat_id"),
                                    typing=False
                                )
                                logger.info(f"Fallback提醒消息已发送: {reminder_content}")
                            except Exception as fallback_error:
                                logger.error(f"Fallback提醒也失败了: {fallback_error}")
                    
                    # 调度提醒事件
                    event_id = f"reminder_{reminder_event.user_id}_{int(reminder_event.reminder_time.timestamp())}"
                    metadata = {
                        "type": "reminder",
                        "user_id": reminder_event.user_id,
                        "sender_name": userinfo.user_nickname,  # 添加发送者昵称
                        "platform": chat.platform,
                        "chat_id": chat.stream_id,
                        "content": reminder_event.content,
                        "confidence": reminder_event.confidence,
                        "created_at": datetime.now().isoformat(),
                        "original_message_id": message.message_info.message_id,
                        "original_message": message.processed_plain_text  # 保存完整的原始消息
                    }
                    
                    success = await event_scheduler.schedule_event(
                        event_id=event_id,
                        trigger_time=reminder_event.reminder_time,
                        callback=reminder_callback,
                        metadata=metadata
                    )
                    
                    if success:
                        logger.info(f"提醒事件调度成功: {event_id}")
                    else:
                        logger.error(f"提醒事件调度失败: {event_id}")
                        
            except Exception as e:
                logger.error(f"智能提醒分析失败: {e}")

            # 3. 兴趣度计算与更新
            interested_rate, is_mentioned, keywords = await _calculate_interest(message)
            message.interest_value = interested_rate
            message.is_mentioned = is_mentioned

            await self.storage.store_message(message, chat)

            subheartflow: SubHeartflow = await heartflow.get_or_create_subheartflow(chat.stream_id)  # type: ignore

            # subheartflow.add_message_to_normal_chat_cache(message, interested_rate, is_mentioned)
            if global_config.mood.enable_mood:
                chat_mood = mood_manager.get_mood_by_chat_id(subheartflow.chat_id)
                asyncio.create_task(chat_mood.update_mood_by_message(message, interested_rate))

            # 3. 日志记录
            mes_name = chat.group_info.group_name if chat.group_info else "私聊"

            # 如果消息中包含图片标识，则将 [picid:...] 替换为 [图片]
            picid_pattern = r"\[picid:([^\]]+)\]"
            processed_plain_text = re.sub(picid_pattern, "[图片]", message.processed_plain_text)

            # 应用用户引用格式替换，将回复<aaa:bbb>和@<aaa:bbb>格式转换为可读格式
            processed_plain_text = replace_user_references_sync(
                processed_plain_text,
                message.message_info.platform,  # type: ignore
                replace_bot_name=True,
            )

            if keywords:
                logger.info(
                    f"[{mes_name}]{userinfo.user_nickname}:{processed_plain_text}[兴趣度：{interested_rate:.2f}][关键词：{keywords}]"
                )  # type: ignore
            else:
                logger.info(
                    f"[{mes_name}]{userinfo.user_nickname}:{processed_plain_text}[兴趣度：{interested_rate:.2f}]"
                )  # type: ignore

            _ = Person.register_person(platform=message.message_info.platform, user_id=message.message_info.user_info.user_id,nickname=userinfo.user_nickname) # type: ignore

        except Exception as e:
            logger.error(f"消息处理失败: {e}")
            print(traceback.format_exc())
