import time
import traceback
import orjson
import re
from typing import TYPE_CHECKING, Dict, Any

from src.common.logger import get_logger
from src.plugin_system.base.component_types import ChatMode
from ..hfc_context import HfcContext
from .events import ProactiveTriggerEvent
from src.plugin_system.apis import generator_api
from src.plugin_system.apis.generator_api import process_human_text
from src.schedule.schedule_manager import schedule_manager
from src.plugin_system import tool_api
from src.plugin_system.base.component_types import ComponentType
from src.config.config import global_config
from src.chat.utils.chat_message_builder import get_raw_msg_before_timestamp_with_chat, build_readable_messages_with_id
from src.mood.mood_manager import mood_manager
from src.common.database.sqlalchemy_database_api import store_action_info, db_get
from src.common.database.sqlalchemy_models import Messages

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
            # 如果是提醒事件，直接使用当前上下文执行at_user动作
            if trigger_event.source == "reminder_system":
                # 1. 获取上下文信息
                metadata = trigger_event.metadata or {}
                reminder_content = trigger_event.reason.replace("定时提醒：", "").strip()

                # 2. 使用LLM智能解析目标用户名
                target_user_name = None
                
                # 首先尝试从完整的原始信息中解析（如果有的话）
                full_content = trigger_event.reason
                logger.info(f"{self.context.log_prefix} 解析提醒内容: '{full_content}'")
                
                sender_name = metadata.get("sender_name")
                target_user_name = await self._extract_target_user_with_llm(full_content, sender_name)

                if not target_user_name:
                    logger.warning(f"无法从提醒 '{reminder_content}' 中确定目标用户，回退")
                    # 回退到生成普通提醒消息
                    fallback_action = {
                        "action_type": "proactive_reply",
                        "action_data": {"topic": f"定时提醒：{reminder_content}"},
                        "action_message": metadata
                    }
                    await self._generate_reminder_proactive_reply(fallback_action, trigger_event, reminder_content)
                    return

                # 3. 直接使用当前上下文的cycle_processor执行at_user动作
                try:
                    success, _, _ = await self.cycle_processor._handle_action(
                        action="at_user",
                        reasoning="执行定时提醒",
                        action_data={
                            "user_name": target_user_name,
                            "at_message": reminder_content
                        },
                        cycle_timers={},
                        thinking_id="",
                        action_message=metadata,
                    )
                    if success:
                        logger.info(f"{self.context.log_prefix} 成功执行定时提醒艾特用户 {target_user_name}")
                        return
                    else:
                        raise Exception("at_user action failed")
                except Exception as e:
                    logger.warning(f"{self.context.log_prefix} at_user动作执行失败: {e}，回退到专用提醒回复")
                    # 回退到专用的定时提醒回复
                    fallback_action = {
                        "action_type": "proactive_reply",
                        "action_data": {"topic": f"定时提醒：{reminder_content}"},
                        "action_message": metadata
                    }
                    await self._generate_reminder_proactive_reply(fallback_action, trigger_event, reminder_content)
                    return

            else:
                # 对于其他来源的主动思考，正常调用规划器
                actions, _ = await self.cycle_processor.action_planner.plan(mode=ChatMode.PROACTIVE)
                action_result = actions[0] if actions else {}
                action_type = action_result.get("action_type")

                if action_type == "proactive_reply":
                    await self._generate_proactive_content_and_send(action_result, trigger_event)
                elif action_type not in ["do_nothing", "no_action"]:
                    await self.cycle_processor._handle_action(
                        action=action_result["action_type"],
                        reasoning=action_result.get("reasoning", ""),
                        action_data=action_result.get("action_data", {}),
                        cycle_timers={},
                        thinking_id="",
                        action_message=action_result.get("action_message")
                    )
                else:
                    logger.info(f"{self.context.log_prefix} 主动思考决策: 保持沉默")
        
        except Exception as e:
            logger.error(f"{self.context.log_prefix} 主动思考执行异常: {e}")
            logger.error(traceback.format_exc())
    async def _extract_target_user_with_llm(self, reminder_content: str, sender_name: str) -> str:
        """
        使用LLM从提醒内容中提取目标用户名

        Args:
            reminder_content: 完整的提醒内容
            sender_name: 消息发送者的昵称

        Returns:
            提取出的用户名，如果找不到则返回None
        """
        try:
            from src.llm_models.utils_model import LLMRequest
            from src.config.config import model_config

            bot_name = global_config.bot.nickname
            user_extraction_prompt = f'''
从以下提醒消息中提取需要被提醒的目标用户名。

**重要认知**:
- 你的名字是"{bot_name}"。当消息中提到"{bot_name}"时，通常是在称呼你。
- 消息的发送者是"{sender_name}"。当消息中出现"我"、"咱"等第一人称代词时，指代的就是"{sender_name}"。

提醒消息: "{reminder_content}"

规则:
1. 分析消息，找出真正需要被提醒的人。
2. 如果提醒目标是第一人称（如"我"），那么目标就是发送者"{sender_name}"。
3. **绝对不能**提取你自己的名字("{bot_name}")作为目标。
4. 只提取最关键的人名，不要包含多余的词语。
5. 如果没有明确的提醒目标（既不是其他人，也不是发送者自己），请回答"无"。

示例:
- 消息: "定时提醒：{bot_name}，10分钟后提醒我去打深渊" -> "{sender_name}"
- 消息: "定时提醒：{bot_name}，提醒阿范一分钟后去写模组" -> "阿范"
- 消息: "定时提醒：一分钟后提醒一闪喝水" -> "一闪"
- 消息: "定时提醒：喝水" -> "无"
- 消息: "定时提醒：{bot_name}，记得休息" -> "无"

请直接输出提取到的用户名，如果不存在则输出"无"。
'''

            llm_request = LLMRequest(
                model_set=model_config.model_task_config.utils_small,
                request_type="reminder_user_extraction"
            )

            response, _ = await llm_request.generate_response_async(prompt=user_extraction_prompt)

            if response and response.strip() != "无":
                logger.info(f"LLM成功提取目标用户: '{response.strip()}'")
                return response.strip()
            else:
                logger.warning(f"LLM未能从 '{reminder_content}' 中提取目标用户")
                return None

        except Exception as e:
            logger.error(f"使用LLM提取用户名时出错: {e}")
            return None

    async def _generate_reminder_proactive_reply(self, action_result: Dict[str, Any], trigger_event: ProactiveTriggerEvent, reminder_content: str):
        """
        为定时提醒事件生成专用的主动回复
        
        Args:
            action_result: 动作结果
            trigger_event: 触发事件
            reminder_content: 提醒内容
        """
        try:
            logger.info(f"{self.context.log_prefix} 生成定时提醒专用回复: '{reminder_content}'")

            # 获取基本信息
            bot_name = global_config.bot.nickname
            personality = global_config.personality
            identity_block = (
                f"你的名字是{bot_name}。\n"
                f"关于你：{personality.personality_core}，并且{personality.personality_side}。\n"
                f"你的身份是{personality.identity}，平时说话风格是{personality.reply_style}。"
            )
            mood_block = f"你现在的心情是：{mood_manager.get_mood_by_chat_id(self.context.stream_id).mood_state}"

            # 获取日程信息
            schedule_block = "你今天没有日程安排。"
            if global_config.planning_system.schedule_enable:
                if current_activity := schedule_manager.get_current_activity():
                    schedule_block = f"你当前正在：{current_activity}。"

            # 为定时提醒定制的专用提示词
            reminder_prompt = f"""
## 你的角色
{identity_block}

## 你的心情
{mood_block}

## 你今天的日程安排
{schedule_block}

## 定时提醒任务
你收到了一个定时提醒："{reminder_content}"
这是一个自动触发的提醒事件，你需要根据提醒内容发送一条友好的提醒消息。

## 任务要求
- 这是一个定时提醒，要体现出你的贴心和关怀
- 根据提醒内容的具体情况（如"喝水"、"休息"等）给出相应的提醒
- 保持你一贯的温暖、俏皮风格
- 可以加上一些鼓励或关心的话语
- 直接输出提醒消息，不要解释为什么要提醒

请生成一条温暖贴心的提醒消息。
"""

            response_text = await generator_api.generate_response_custom(
                chat_stream=self.context.chat_stream,
                prompt=reminder_prompt,
                request_type="chat.replyer.reminder",
            )

            if response_text:
                response_set = process_human_text(
                    content=response_text,
                    enable_splitter=global_config.response_splitter.enable,
                    enable_chinese_typo=global_config.chinese_typo.enable,
                )
                await self.cycle_processor.response_handler.send_response(
                    response_set, time.time(), action_result.get("action_message")
                )
                await store_action_info(
                    chat_stream=self.context.chat_stream,
                    action_name="reminder_reply",
                    action_data={"reminder_content": reminder_content, "response": response_text},
                    action_prompt_display=f"定时提醒回复: {reminder_content}",
                    action_done=True,
                )
                logger.info(f"{self.context.log_prefix} 成功发送定时提醒回复: {response_text}")
            else:
                logger.error(f"{self.context.log_prefix} 定时提醒回复生成失败。")

        except Exception as e:
            logger.error(f"{self.context.log_prefix} 生成定时提醒回复时异常: {e}")
            logger.error(traceback.format_exc())


    async def _get_reminder_context(self, message_id: str) -> str:
        """获取提醒消息的上下文"""
        try:
            # 只获取那一条消息
            message_record = await db_get(Messages, {"message_id": message_id}, single_result=True)
            if message_record:
                # 使用 build_readable_messages_with_id 来格式化单条消息
                chat_context_block, _ = build_readable_messages_with_id(messages=[message_record])
                return chat_context_block
            return "无法加载相关的聊天记录。"
        except Exception as e:
            logger.error(f"{self.context.log_prefix} 获取提醒上下文失败: {e}")
            return "无法加载相关的聊天记录。"
    
    async def _generate_proactive_content_and_send(self, action_result: Dict[str, Any], trigger_event: ProactiveTriggerEvent):
        """
        获取实时信息，构建最终的生成提示词，并生成和发送主动回复。

        Args:
            action_result (Dict[str, Any]): 规划器返回的动作结果。
            trigger_event (ProactiveTriggerEvent): 触发事件。
        """
        try:
            topic = action_result.get("action_data", {}).get("topic", "随便聊聊")
            logger.info(f"{self.context.log_prefix} 主动思考确定主题: '{topic}'")

            schedule_block = "你今天没有日程安排。"
            if global_config.planning_system.schedule_enable:
                if current_activity := schedule_manager.get_current_activity():
                    schedule_block = f"你当前正在：{current_activity}。"

            news_block = "暂时没有获取到最新资讯。"
            if trigger_event.source != "reminder_system":
                try:
                    web_search_tool = tool_api.get_tool_instance("web_search")
                    if web_search_tool:
                        try:
                            search_result_dict = await web_search_tool.execute(search_query=topic, max_results=10)
                        except TypeError:
                            try:
                                search_result_dict = await web_search_tool.execute(keyword=topic, max_results=10)
                            except TypeError:
                                logger.warning(f"{self.context.log_prefix} 网络搜索工具参数不匹配，跳过搜索")
                                news_block = "跳过网络搜索。"
                                search_result_dict = None
                        
                        if search_result_dict and not search_result_dict.get("error"):
                            news_block = search_result_dict.get("content", "未能提取有效资讯。")
                        elif search_result_dict:
                            logger.warning(f"{self.context.log_prefix} 网络搜索返回错误: {search_result_dict.get('error')}")
                    else:
                        logger.warning(f"{self.context.log_prefix} 未找到 web_search 工具实例。")
                except Exception as e:
                    logger.error(f"{self.context.log_prefix} 主动思考时网络搜索失败: {e}")

            if trigger_event.source == "reminder_system" and trigger_event.related_message_id:
                chat_context_block = await self._get_reminder_context(trigger_event.related_message_id)
            else:
                message_list = get_raw_msg_before_timestamp_with_chat(
                    chat_id=self.context.stream_id,
                    timestamp=time.time(),
                    limit=int(global_config.chat.max_context_size * 0.3),
                )
                chat_context_block, _ = build_readable_messages_with_id(messages=message_list)

            from src.llm_models.utils_model import LLMRequest
            from src.config.config import model_config
            
            bot_name = global_config.bot.nickname
            
            confirmation_prompt = f"""# 主动回复二次确认

## 基本信息
你的名字是{bot_name}，准备主动发起关于"{topic}"的话题。

## 最近的聊天内容
{chat_context_block}

## 合理判断标准
请检查以下条件，如果**大部分条件都合理**就可以回复：

1. **时间合理性**：当前时间是否在深夜（凌晨2点-6点）这种不适合主动聊天的时段？
2. **内容价值**：这个话题"{topic}"是否有意义，不是完全无关紧要的内容？
3. **重复避免**：你准备说的话题是否与最近2条消息明显重复？
4. **自然性**：在当前上下文中主动提起这个话题是否自然合理？

## 输出要求
如果判断应该跳过（比如深夜时段、完全无意义话题、明显重复内容），输出：SKIP_PROACTIVE_REPLY
其他情况都应该输出：PROCEED_TO_REPLY

请严格按照上述格式输出，不要添加任何解释。"""

            planner_llm = LLMRequest(
                model_set=model_config.model_task_config.planner,
                request_type="planner"
            )
            
            confirmation_result, _ = await planner_llm.generate_response_async(prompt=confirmation_prompt)
            
            if not confirmation_result or "SKIP_PROACTIVE_REPLY" in confirmation_result:
                logger.info(f"{self.context.log_prefix} 决策模型二次确认决定跳过主动回复")
                return
                
            bot_name = global_config.bot.nickname
            personality = global_config.personality
            identity_block = (
                f"你的名字是{bot_name}。\n"
                f"关于你：{personality.personality_core}，并且{personality.personality_side}。\n"
                f"你的身份是{personality.identity}，平时说话风格是{personality.reply_style}。"
            )
            mood_block = f"你现在的心情是：{mood_manager.get_mood_by_chat_id(self.context.stream_id).mood_state}"

            final_prompt = f"""
## 你的角色
{identity_block}

## 你的心情
{mood_block}

## 你今天的日程安排
{schedule_block}

## 关于你准备讨论的话题"{topic}"的最新信息
{news_block}

## 最近的聊天内容
{chat_context_block}

## 任务
你现在想要主动说些什么。话题是"{topic}"，但这只是一个参考方向。

根据最近的聊天内容，你可以：
- 如果是想关心朋友，就自然地询问他们的情况
- 如果想起了之前的话题，就问问后来怎么样了
- 如果有什么想分享的想法，就自然地开启话题
- 如果只是想闲聊，就随意地说些什么

## 要求
- 像真正的朋友一样，自然地表达关心或好奇
- 不要过于正式，要口语化和亲切
- 结合你的角色设定，保持温暖的风格
- 直接输出你想说的话，不要解释为什么要说

请输出一条简短、自然的主动发言。
"""

            response_text = await generator_api.generate_response_custom(
                chat_stream=self.context.chat_stream,
                prompt=final_prompt,
                request_type="chat.replyer.proactive",
            )

            if response_text:
                response_set = process_human_text(
                    content=response_text,
                    enable_splitter=global_config.response_splitter.enable,
                    enable_chinese_typo=global_config.chinese_typo.enable,
                )
                await self.cycle_processor.response_handler.send_response(
                    response_set, time.time(), action_result.get("action_message")
                )
                await store_action_info(
                    chat_stream=self.context.chat_stream,
                    action_name="proactive_reply",
                    action_data={"topic": topic, "response": response_text},
                    action_prompt_display=f"主动发起对话: {topic}",
                    action_done=True,
                )
            else:
                logger.error(f"{self.context.log_prefix} 主动思考生成回复失败。")

        except Exception as e:
            logger.error(f"{self.context.log_prefix} 生成主动回复内容时异常: {e}")
            logger.error(traceback.format_exc())
