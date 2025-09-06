import time
import traceback
from typing import TYPE_CHECKING

from src.common.logger import get_logger
from src.plugin_system.base.component_types import ChatMode
from ..hfc_context import HfcContext
from .events import ProactiveTriggerEvent
from src.plugin_system.apis import generator_api

if TYPE_CHECKING:
    from ..cycle_processor import CycleProcessor

logger = get_logger("hfc")


class ProactiveThinker:
    """
    主动思考器，负责处理和执行主动思考事件。
    当接收到 ProactiveTriggerEvent 时，它会根据事件内容进行一系列决策和操作，
    例如调整情绪、调用规划器生成行动，并最终可能产生一个主动的回复。
    """
    def __init__(self, context: HfcContext, cycle_processor: "CycleProcessor"):
        """
        初始化主动思考器。

        Args:
            context (HfcContext): HFC聊天上下文对象，提供了当前聊天会话的所有背景信息。
            cycle_processor (CycleProcessor): 循环处理器，用于执行主动思考后产生的动作。

        功能说明:
        - 接收并处理主动思考事件 (ProactiveTriggerEvent)。
        - 在思考前根据事件类型执行预处理操作，如修改当前情绪状态。
        - 调用行动规划器 (Action Planner) 来决定下一步应该做什么。
        - 如果规划结果是发送消息，则调用生成器API生成回复并发送。
        """
        self.context = context
        self.cycle_processor = cycle_processor

    async def think(self, trigger_event: ProactiveTriggerEvent):
        """
        主动思考的统一入口API。
        这是外部触发主动思考时调用的主要方法。

        Args:
            trigger_event (ProactiveTriggerEvent): 描述触发上下文的事件对象，包含了思考的来源和原因。
        """
        logger.info(
            f"{self.context.log_prefix} 接收到主动思考事件: "
            f"来源='{trigger_event.source}', 原因='{trigger_event.reason}'"
        )

        try:
            # 步骤 1: 根据事件类型执行思考前的准备工作，例如调整情绪。
            await self._prepare_for_thinking(trigger_event)

            # 步骤 2: 执行核心的思考和决策逻辑。
            await self._execute_proactive_thinking(trigger_event)

        except Exception as e:
            # 捕获并记录在思考过程中发生的任何异常。
            logger.error(f"{self.context.log_prefix} 主动思考 think 方法执行异常: {e}")
            logger.error(traceback.format_exc())

    async def _prepare_for_thinking(self, trigger_event: ProactiveTriggerEvent):
        """
        根据事件类型，在正式思考前执行准备工作。
        目前主要是处理来自失眠管理器的事件，并据此调整情绪。

        Args:
            trigger_event (ProactiveTriggerEvent): 触发事件。
        """
        # 目前只处理来自失眠管理器(insomnia_manager)的事件
        if trigger_event.source != "insomnia_manager":
            return

        try:
            # 动态导入情绪管理器，避免循环依赖
            from src.mood.mood_manager import mood_manager

            # 获取当前聊天的情绪对象
            mood_obj = mood_manager.get_mood_by_chat_id(self.context.stream_id)
            new_mood = None

            # 根据失眠的不同原因设置对应的情绪
            if trigger_event.reason == "low_pressure":
                new_mood = "精力过剩，毫无睡意"
            elif trigger_event.reason == "random":
                new_mood = "深夜emo，胡思乱想"
            elif trigger_event.reason == "goodnight":
                new_mood = "有点困了，准备睡觉了"

            # 如果成功匹配到了新的情绪，则更新情绪状态
            if new_mood:
                mood_obj.mood_state = new_mood
                mood_obj.last_change_time = time.time()
                logger.info(
                    f"{self.context.log_prefix} 因 '{trigger_event.reason}'，"
                    f"情绪状态被强制更新为: {mood_obj.mood_state}"
                )

        except Exception as e:
            logger.error(f"{self.context.log_prefix} 设置失眠情绪时出错: {e}")

    async def _execute_proactive_thinking(self, trigger_event: ProactiveTriggerEvent):
        """
        执行主动思考的核心逻辑。
        它会调用规划器来决定是否要采取行动，以及采取什么行动。

        Args:
            trigger_event (ProactiveTriggerEvent): 触发事件。
        """
        try:
            # 调用规划器的 PROACTIVE 模式，让其决定下一步的行动
            actions, target_message = await self.cycle_processor.action_planner.plan(mode=ChatMode.PROACTIVE)

            # 通常只关心规划出的第一个动作
            action_result = actions[0] if actions else {}

            # 检查规划出的动作是否是“什么都不做”
            if action_result and action_result.get("action_type") != "do_nothing":
                # 如果动作是“回复”
                if action_result.get("action_type") == "reply":
                    # 调用生成器API来创建回复内容
                    success, response_set, _ = await generator_api.generate_reply(
                        chat_stream=self.context.chat_stream,
                        reply_message=action_result["action_message"],
                        available_actions={},  # 主动回复不考虑工具使用
                        enable_tool=False,
                        request_type="chat.replyer.proactive", # 标记请求类型
                        from_plugin=False,
                    )
                    # 如果成功生成回复，则发送出去
                    if success and response_set:
                        await self.cycle_processor.response_handler.send_response(
                            response_set, time.time(), action_result["action_message"]
                        )
            else:
                # 如果规划结果是“什么都不做”，则记录日志
                logger.info(f"{self.context.log_prefix} 主动思考决策: 保持沉默")

        except Exception as e:
            logger.error(f"{self.context.log_prefix} 主动思考执行异常: {e}")
            logger.error(traceback.format_exc())
