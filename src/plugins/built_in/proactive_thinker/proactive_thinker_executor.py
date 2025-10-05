import time
from datetime import datetime
from typing import Any

import orjson

from src.chat.utils.chat_message_builder import get_actions_by_timestamp_with_chat
from src.common.logger import get_logger
from src.config.config import global_config, model_config
from src.mood.mood_manager import mood_manager
from src.person_info.person_info import get_person_info_manager
from src.plugin_system.apis import (
    chat_api,
    database_api,
    generator_api,
    llm_api,
    message_api,
    person_api,
    schedule_api,
    send_api,
)

logger = get_logger(__name__)


class ProactiveThinkerExecutor:
    """
    主动思考执行器 V2
    - 统一执行入口
    - 引入决策模块，判断是否及如何发起对话
    - 结合人设、日程、关系信息生成更具情境的对话
    """

    def __init__(self):
        """
        初始化 ProactiveThinkerExecutor 实例。
        目前无需初始化操作。
        """
        pass

    async def execute(self, stream_id: str, start_mode: str = "wake_up"):
        """
        统一执行入口
        Args:
            stream_id: 聊天流ID
            start_mode: 启动模式, 'cold_start' 或 'wake_up'
        """
        logger.info(f"开始为聊天流 {stream_id} 执行主动思考，模式: {start_mode}")

        # 1. 信息收集
        context = await self._gather_context(stream_id)
        if not context:
            return

        # 2. 决策阶段
        decision_result = await self._make_decision(context, start_mode)

        if not decision_result or not decision_result.get("should_reply"):
            reason = decision_result.get("reason", "未提供") if decision_result else "决策过程返回None"
            logger.info(f"决策结果为：不回复。原因: {reason}")
            await database_api.store_action_info(
                chat_stream=self._get_stream_from_id(stream_id),
                action_name="proactive_decision",
                action_prompt_display=f"主动思考决定不回复,原因: {reason}",
                action_done=True,
                action_data=decision_result,
            )
            return

        # 3. 规划与执行阶段
        topic = decision_result.get("topic", "打个招呼")
        reason = decision_result.get("reason", "无")
        await database_api.store_action_info(
            chat_stream=self._get_stream_from_id(stream_id),
            action_name="proactive_decision",
            action_prompt_display=f"主动思考决定回复,原因: {reason},话题:{topic}",
            action_done=True,
            action_data=decision_result,
        )
        logger.info(f"决策结果为：回复。话题: {topic}")

        plan_prompt = self._build_plan_prompt(context, start_mode, topic, reason)

        is_success, response, _, _ = await llm_api.generate_with_model(
            prompt=plan_prompt, model_config=model_config.model_task_config.replyer
        )

        if is_success and response:
            stream = self._get_stream_from_id(stream_id)
            if stream:
                # 使用消息分割器处理并发送消息
                reply_set = generator_api.process_human_text(response, enable_splitter=True, enable_chinese_typo=False)
                for reply_type, content in reply_set:
                    if reply_type == "text":
                        await send_api.text_to_stream(stream_id=stream.stream_id, text=content)
            else:
                logger.warning(f"无法发送消息，因为找不到 stream_id 为 {stream_id} 的聊天流")

    def _get_stream_from_id(self, stream_id: str):
        """
        根据 stream_id 解析并获取对应的聊天流对象。

        Args:
            stream_id: 聊天流的唯一标识符，格式为 "platform:chat_id:stream_type"。

        Returns:
            对应的 ChatStream 对象，如果解析失败或找不到则返回 None。
        """
        try:
            platform, chat_id, stream_type = stream_id.split(":")
            if stream_type == "private":
                return chat_api.ChatManager.get_private_stream_by_user_id(platform=platform, user_id=chat_id)
            elif stream_type == "group":
                return chat_api.ChatManager.get_group_stream_by_group_id(platform=platform, group_id=chat_id)
        except Exception as e:
            logger.error(f"获取 stream_id ({stream_id}) 失败: {e}")
            return None

    async def _gather_context(self, stream_id: str) -> dict[str, Any] | None:
        """
        收集构建决策和规划提示词所需的所有上下文信息。

        此函数会根据聊天流是私聊还是群聊，收集不同的信息，
        包括但不限于日程、聊天历史、人设、关系信息等。

        Args:
            stream_id: 聊天流ID。

        Returns:
            一个包含所有上下文信息的字典，如果找不到聊天流则返回 None。
        """
        stream = self._get_stream_from_id(stream_id)
        if not stream:
            logger.warning(f"无法找到 stream_id 为 {stream_id} 的聊天流")
            return None

        # 1. 收集通用信息 (日程, 聊天历史, 动作历史)
        schedules = await schedule_api.ScheduleAPI.get_today_schedule()
        schedule_context = (
            "\n".join([f"- {s.get('time_range', '未知时间')}: {s.get('activity', '未知活动')}" for s in schedules])
            if schedules
            else "今天没有日程安排。"
        )

        recent_messages = await message_api.get_recent_messages(stream.stream_id,limit=50,limit_mode="latest",hours=12)
        recent_chat_history = (
            await message_api.build_readable_messages_to_str(recent_messages) if recent_messages else "无"
        )

        action_history_list = await get_actions_by_timestamp_with_chat(
            chat_id=stream.stream_id,
            timestamp_start=time.time() - 3600 * 24,  #过去24小时
            timestamp_end=time.time(),
            limit=7,
        )

        action_history_context = (
            "\n".join([f"- {a['action_data']}" for a in action_history_list if isinstance(a, dict)])
            if isinstance(action_history_list, list)
            else "无"
        )

        # 2. 构建基础上下文
        mood_state = "暂时没有"
        if global_config.mood.enable_mood:
            try:
                mood_state = mood_manager.get_mood_by_chat_id(stream.stream_id).mood_state
            except Exception as e:
                logger.error(f"获取情绪失败,原因:{e}")
        base_context = {
            "schedule_context": schedule_context,
            "recent_chat_history": recent_chat_history,
            "action_history_context": action_history_context,
            "mood_state": mood_state,
            "persona": {
                "core": global_config.personality.personality_core,
                "side": global_config.personality.personality_side,
                "identity": global_config.personality.identity,
            },
            "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        # 3. 根据聊天类型补充特定上下文
        if stream.group_info:  # 群聊场景
            base_context.update(
                {
                    "chat_type": "group",
                    "group_info": {"group_name": stream.group_info.group_name, "group_id": stream.group_info.group_id},
                }
            )
            return base_context
        elif stream.user_info:  # 私聊场景
            user_info = stream.user_info
            if not user_info.platform or not user_info.user_id:
                logger.warning(f"Stream {stream_id} 的 user_info 不完整")
                return None

            person_id = person_api.get_person_id(user_info.platform, int(user_info.user_id))
            person_info_manager = get_person_info_manager()

            # 获取关系信息
            short_impression = await person_info_manager.get_value(person_id, "short_impression") or "无"
            impression = await person_info_manager.get_value(person_id, "impression") or "无"
            attitude = await person_info_manager.get_value(person_id, "attitude") or 50

            base_context.update(
                {
                    "chat_type": "private",
                    "person_id": person_id,
                    "user_info": user_info,
                    "relationship": {
                        "short_impression": short_impression,
                        "impression": impression,
                        "attitude": attitude,
                    },
                }
            )
            return base_context
        else:
            logger.warning(f"Stream {stream_id} 既没有 group_info 也没有 user_info")
            return None

    def _build_decision_prompt(self, context: dict[str, Any], start_mode: str) -> str:
        """
        根据收集到的上下文信息，构建用于决策的提示词。

        Args:
            context: 包含所有上下文信息的字典。
            start_mode: 启动模式 ('cold_start' 或 'wake_up')。

        Returns:
            构建完成的决策提示词字符串。
        """
        chat_type = context["chat_type"]
        persona = context["persona"]

        # 构建通用头部
        prompt = f"""
# 角色
你的名字是{global_config.bot.nickname}，你的人设如下：
- 核心人设: {persona["core"]}
- 侧面人设: {persona["side"]}
- 身份: {persona["identity"]}

你的当前情绪状态是: {context["mood_state"]}

# 你最近的相关决策历史 (供参考)
{context["action_history_context"]}
"""
        # 根据聊天类型构建任务和情境
        if chat_type == "private":
            user_info = context["user_info"]
            relationship = context["relationship"]
            prompt += f"""
# 任务
现在是 {context["current_time"]}，你需要根据当前的情境，决定是否要主动向用户 '{user_info.user_nickname}' 发起对话。

# 情境分析
1.  **启动模式**: {start_mode} ({"初次见面/很久未见" if start_mode == "cold_start" else "日常唤醒"})
2.  **你的日程**:
{context["schedule_context"]}
3.  **你和Ta的关系**:
    - 简短印象: {relationship["short_impression"]}
    - 详细印象: {relationship["impression"]}
    - 好感度: {relationship["attitude"]}/100
4.  **最近的聊天摘要**:
{context["recent_chat_history"]}
"""
        elif chat_type == "group":
            group_info = context["group_info"]
            prompt += f"""
# 任务
现在是 {context["current_time"]}，你需要根据当前的情境，决定是否要主动向群聊 '{group_info["group_name"]}' 发起对话。

# 情境分析
1.  **启动模式**: {start_mode} ({"首次加入/很久未发言" if start_mode == "cold_start" else "日常唤醒"})
2.  **你的日程**:
{context["schedule_context"]}
3.  **群聊信息**:
    - 群名称: {group_info["group_name"]}
4.  **最近的聊天摘要**:
{context["recent_chat_history"]}
"""
        # 构建通用尾部
        prompt += """
# 决策指令
请综合以上所有信息，以稳定、真实、拟人的方式做出决策。你的决策需要以JSON格式输出，包含以下字段：
- `should_reply`: bool, 是否应该发起对话。
- `topic`: str, 如果 `should_reply` 为 true，你打算聊什么话题？
- `reason`: str, 做出此决策的简要理由。

# 决策原则
- **谨慎对待未回复的对话**: 在发起新话题前，请检查【最近的聊天摘要】。如果最后一条消息是你自己发送的，请仔细评估等待的时间和上下文，判断再次主动发起对话是否礼貌和自然。如果等待时间很短（例如几分钟或半小时内），通常应该选择“不回复”。
- **优先利用上下文**: 优先从【情境分析】中已有的信息（如最近的聊天摘要、你的日程、你对Ta的关系印象）寻找自然的话题切入点。
- **简单问候作为备选**: 如果上下文中没有合适的话题，可以生成一个简单、真诚的日常问候（例如“在忙吗？”，“下午好呀~”）。
- **避免抽象**: 避免创造过于复杂、抽象或需要对方思考很久才能明白的话题。目标是轻松、自然地开启对话。
- **避免过于频繁**: 如果你最近（尤其是在最近的几次决策中）已经主动发起过对话，请倾向于选择“不回复”，除非有非常重要和紧急的事情。
- **如果上下文中只有你的消息而没有别人的消息**:选择不回复,以防刷屏或者打扰到别人


---
示例1 (基于上下文):
{{
  "should_reply": true,
  "topic": "关心一下Ta昨天提到的那个项目进展如何了",
  "reason": "用户昨天在聊天中提到了一个重要的项目，现在主动关心一下进展，会显得很体贴，也能自然地开启对话。"
}}

示例2 (简单问候):
{{
  "should_reply": true,
  "topic": "打个招呼，问问Ta现在在忙些什么",
  "reason": "最近没有聊天记录，日程也很常规，没有特别的切入点。一个简单的日常问候是最安全和自然的方式来重新连接。"
}}

示例3 (不应回复 - 过于频繁):
{{
  "should_reply": false,
  "topic": null,
  "reason": "虽然群里很活跃，但现在是深夜，而且最近的聊天话题我也不熟悉，没有合适的理由去打扰大家。"
}}

示例4 (不应回复 - 等待回应):
{{
  "should_reply": false,
  "topic": null,
  "reason": "我注意到上一条消息是我几分钟前主动发送的，对方可能正在忙。为了表现出耐心和体贴，我现在最好保持安静，等待对方的回应。"
}}
---

请输出你的决策:
"""
        return prompt

    async def _make_decision(self, context: dict[str, Any], start_mode: str) -> dict[str, Any] | None:
        """
        调用 LLM 进行决策，判断是否应该主动发起对话，以及聊什么话题。

        Args:
            context: 包含所有上下文信息的字典。
            start_mode: 启动模式。

        Returns:
            一个包含决策结果的字典 (例如: {"should_reply": bool, "topic": str, "reason": str})，
            如果决策过程失败则返回 None 或包含错误信息的字典。
        """
        if context["chat_type"] not in ["private", "group"]:
            return {"should_reply": False, "reason": "未知的聊天类型"}

        prompt = self._build_decision_prompt(context, start_mode)

        if global_config.debug.show_prompt:
            logger.info(f"主动思考决策器原始提示词:{prompt}")

        is_success, response, _, _ = await llm_api.generate_with_model(
            prompt=prompt, model_config=model_config.model_task_config.utils
        )

        if not is_success:
            return {"should_reply": False, "reason": "决策模型生成失败"}

        try:
            if global_config.debug.show_prompt:
                logger.info(f"主动思考决策器响应:{response}")
            decision = orjson.loads(response)
            return decision
        except orjson.JSONDecodeError:
            logger.error(f"决策LLM返回的JSON格式无效: {response}")
            return {"should_reply": False, "reason": "决策模型返回格式错误"}

    def _build_private_plan_prompt(self, context: dict[str, Any], start_mode: str, topic: str, reason: str) -> str:
        """
        为私聊场景构建生成对话内容的规划提示词。

        Args:
            context: 上下文信息字典。
            start_mode: 启动模式。
            topic: 决策模块决定的话题。
            reason: 决策模块给出的理由。

        Returns:
            构建完成的私聊规划提示词字符串。
        """
        user_info = context["user_info"]
        relationship = context["relationship"]
        if start_mode == "cold_start":
            return f"""
# 任务
你需要主动向一个新朋友 '{user_info.user_nickname}' 发起对话。这是你们的第一次交流，或者很久没聊了。

# 决策上下文
- **决策理由**: {reason}

# 情境分析
1.  **你的日程**:
{context["schedule_context"]}
2.  **你和Ta的关系**:
    - 简短印象: {relationship["short_impression"]}
    - 详细印象: {relationship["impression"]}
    - 好感度: {relationship["attitude"]}/100
3.  **最近的聊天摘要**:
{context["recent_chat_history"]}
4.  **你最近的相关动作**:
{context["action_history_context"]}

# 对话指引
- 你的目标是“破冰”，让对话自然地开始。
- 你应该围绕这个话题展开: {topic}
- 你的语气应该符合你的人设和你当前的心情({context["mood_state"]})，友好且真诚。
"""
        else:  # wake_up
            return f"""
# 任务
现在是 {context["current_time"]}，你需要主动向你的朋友 '{user_info.user_nickname}' 发起对话。

# 决策上下文
- **决策理由**: {reason}

# 情境分析
1.  **你的日程**:
{context["schedule_context"]}
2.  **你和Ta的关系**:
    - 详细印象: {relationship["impression"]}
    - 好感度: {relationship["attitude"]}/100
3.  **最近的聊天摘要**:
{context["recent_chat_history"]}
4.  **你最近的相关动作**:
{context["action_history_context"]}

# 对话指引
- 你决定和Ta聊聊关于“{topic}”的话题。
- **重要**: 在开始你的话题前，必须先用一句通用的、礼貌的开场白进行问候（例如：“在吗？”、“上午好！”、“晚上好呀~”），然后再自然地衔接你的话题，确保整个回复在一条消息内流畅、自然、像人类的说话方式。
- 请结合以上所有情境信息，自然地开启对话。
- 你的语气应该符合你的人设({context["mood_state"]})以及你对Ta的好感度。
"""

    def _build_group_plan_prompt(self, context: dict[str, Any], topic: str, reason: str) -> str:
        """
        为群聊场景构建生成对话内容的规划提示词。

        Args:
            context: 上下文信息字典。
            topic: 决策模块决定的话题。
            reason: 决策模块给出的理由。

        Returns:
            构建完成的群聊规划提示词字符串。
        """
        group_info = context["group_info"]
        return f"""
# 任务
现在是 {context["current_time"]}，你需要主动向群聊 '{group_info["group_name"]}' 发起对话。

# 决策上下文
- **决策理由**: {reason}

# 情境分析
1.  **你的日程**:
你当前的心情({context["mood_state"]}
{context["schedule_context"]}
2.  **群聊信息**:
    - 群名称: {group_info["group_name"]}
3.  **最近的聊天摘要**:
{context["recent_chat_history"]}
4.  **你最近的相关动作**:
{context["action_history_context"]}

# 对话指引
- 你决定和大家聊聊关于“{topic}”的话题。
- **重要**: 在开始你的话题前，必须先用一句通用的、礼貌的开场白进行问候（例如：“哈喽，大家好呀~”、“下午好！”），然后再自然地衔接你的话题，确保整个回复在一条消息内流畅、自然、像人类的说话方式。
- 你的语气应该更活泼、更具包容性，以吸引更多群成员参与讨论。你的语气应该符合你的人设)。
- 请结合以上所有情境信息，自然地开启对话。
- 可以分享你的看法、提出相关问题，或者开个合适的玩笑。
"""

    def _build_plan_prompt(self, context: dict[str, Any], start_mode: str, topic: str, reason: str) -> str:
        """
        根据聊天类型、启动模式和决策结果，构建最终生成对话内容的规划提示词。

        Args:
            context: 上下文信息字典。
            start_mode: 启动模式。
            topic: 决策模块决定的话题。
            reason: 决策模块给出的理由。

        Returns:
            最终的规划提示词字符串。
        """
        persona = context["persona"]
        chat_type = context["chat_type"]

        # 1. 构建通用角色头部
        prompt = f"""
# 角色
你的名字是{global_config.bot.nickname}，你的人设如下：
- 核心人设: {persona["core"]}
- 侧面人设: {persona["side"]}
- 身份: {persona["identity"]}
"""
        # 2. 根据聊天类型构建特定内容
        if chat_type == "private":
            prompt += self._build_private_plan_prompt(context, start_mode, topic, reason)
        elif chat_type == "group":
            prompt += self._build_group_plan_prompt(context, topic, reason)

        # 3. 添加通用结尾
        final_instructions = """

# 输出要求
- **简洁**: 不要输出任何多余内容（如前缀、后缀、冒号、引号、at/@等）。
- **原创**: 不要重复之前的内容，即使意思相近也不行。
- **直接**: 只输出最终的回复文本本身。
- **风格**: 回复需简短、完整且口语化。

现在，你说："""
        prompt += final_instructions

        if global_config.debug.show_prompt:
            logger.info(f"主动思考回复器原始提示词:{prompt}")
        return prompt
