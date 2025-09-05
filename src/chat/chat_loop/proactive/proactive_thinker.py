import time
import traceback
from typing import TYPE_CHECKING

from src.common.logger import get_logger
from src.plugin_system.base.component_types import ChatMode
from ..hfc_context import HfcContext
from .events import ProactiveTriggerEvent

if TYPE_CHECKING:
    from ..cycle_processor import CycleProcessor

logger = get_logger("hfc")


class ProactiveThinker:
    def __init__(self, context: HfcContext, cycle_processor: "CycleProcessor"):
        """
        初始化主动思考器

        Args:
            context: HFC聊天上下文对象
            cycle_processor: 循环处理器，用于执行主动思考的结果

        功能说明:
        - 接收主动思考事件并执行思考流程
        - 根据事件类型执行不同的前置操作（如修改情绪）
        - 调用planner进行决策并由cycle_processor执行
        """
        self.context = context
        self.cycle_processor = cycle_processor

    async def think(self, trigger_event: ProactiveTriggerEvent):
        """
        统一的API入口，用于触发主动思考

        Args:
            trigger_event: 描述触发上下文的事件对象
        """
        logger.info(f"{self.context.log_prefix} 接收到主动思考事件: "
                    f"来源='{trigger_event.source}', 原因='{trigger_event.reason}'")

        try:
            # 1. 根据事件类型执行前置操作
            await self._prepare_for_thinking(trigger_event)

            # 2. 执行核心思考逻辑
            await self._execute_proactive_thinking(trigger_event)

        except Exception as e:
            logger.error(f"{self.context.log_prefix} 主动思考 think 方法执行异常: {e}")
            logger.error(traceback.format_exc())

    async def _prepare_for_thinking(self, trigger_event: ProactiveTriggerEvent):
        """
        根据事件类型，执行思考前的准备工作，例如修改情绪

        Args:
            trigger_event: 触发事件
        """
        if trigger_event.source != "insomnia_manager":
            return

        try:
            from src.mood.mood_manager import mood_manager
            mood_obj = mood_manager.get_mood_by_chat_id(self.context.stream_id)
            new_mood = None

            if trigger_event.reason == "low_pressure":
                new_mood = "精力过剩，毫无睡意"
            elif trigger_event.reason == "random":
                new_mood = "深夜emo，胡思乱想"
            elif trigger_event.reason == "goodnight":
                new_mood = "有点困了，准备睡觉了"

            if new_mood:
                mood_obj.mood_state = new_mood
                mood_obj.last_change_time = time.time()
                logger.info(f"{self.context.log_prefix} 因 '{trigger_event.reason}'，"
                            f"情绪状态被强制更新为: {mood_obj.mood_state}")

        except Exception as e:
            logger.error(f"{self.context.log_prefix} 设置失眠情绪时出错: {e}")

    async def _execute_proactive_thinking(self, trigger_event: ProactiveTriggerEvent):
        """
        执行主动思考的核心逻辑

        Args:
            trigger_event: 触发事件
        """
        try:
            # 直接调用 planner 的 PROACTIVE 模式
            actions, target_message = await self.cycle_processor.action_planner.plan(
                mode=ChatMode.PROACTIVE
            )
            
            # 获取第一个规划出的动作作为主要决策
            action_result = actions[0] if actions else {}

            # 如果决策不是 do_nothing，则执行
            if action_result and action_result.get("action_type") != "do_nothing":

                # 在主动思考时，如果 target_message 为 None，则默认选取最新 message 作为 target_message
                if target_message is None and self.context.chat_stream and self.context.chat_stream.context:
                    from src.chat.message_receive.message import MessageRecv
                    latest_message = self.context.chat_stream.context.get_last_message()
                    if isinstance(latest_message, MessageRecv):
                        user_info = latest_message.message_info.user_info
                        target_message = {
                            "chat_info_platform": latest_message.message_info.platform,
                            "user_platform": user_info.platform if user_info else None,
                            "user_id": user_info.user_id if user_info else None,
                            "processed_plain_text": latest_message.processed_plain_text,
                            "is_mentioned": latest_message.is_mentioned,
                        }

                # 将决策结果交给 cycle_processor 的后续流程处理
                await self.cycle_processor.execute_plan(action_result, target_message)
            else:
                logger.info(f"{self.context.log_prefix} 主动思考决策: 保持沉默")

        except Exception as e:
            logger.error(f"{self.context.log_prefix} 主动思考执行异常: {e}")
            logger.error(traceback.format_exc())
