"""
Kokoro Flow Chatter - 提示词构建器

使用项目统一的 Prompt 管理系统构建提示词
"""

import time
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from src.chat.utils.prompt import global_prompt_manager
from src.common.logger import get_logger
from src.config.config import global_config

from ..models import EventType, MentalLogEntry, SessionStatus
from ..session import KokoroSession

# 导入模板注册（确保模板被注册到 global_prompt_manager）
from . import prompts as _  # noqa: F401
from .prompts import PROMPT_NAMES

if TYPE_CHECKING:
    from src.chat.message_receive.chat_stream import ChatStream

logger = get_logger("kfc_prompt_builder")


class PromptBuilder:
    """
    提示词构建器
    
    使用统一的 Prompt 管理系统构建提示词：
    1. 构建活动流（从 mental_log 生成线性叙事）
    2. 构建当前情况描述
    3. 使用 global_prompt_manager 格式化最终提示词
    """
    
    def __init__(self):
        self._context_builder = None
    
    async def build_planner_prompt(
        self,
        session: KokoroSession,
        user_name: str,
        situation_type: str = "new_message",
        chat_stream: Optional["ChatStream"] = None,
        available_actions: Optional[dict] = None,
        extra_context: Optional[dict] = None,
    ) -> str:
        """
        构建规划器提示词（用于生成行动计划）
        
        Args:
            session: 会话对象
            user_name: 用户名称
            situation_type: 情况类型 (new_message/reply_in_time/reply_late/timeout/proactive)
            chat_stream: 聊天流对象
            available_actions: 可用动作字典
            extra_context: 额外上下文（如 trigger_reason）
            
        Returns:
            完整的规划器提示词
        """
        extra_context = extra_context or {}
        
        # 获取 user_id（从 session 中）
        user_id = session.user_id if session else None
        
        # 1. 构建人设块
        persona_block = self._build_persona_block()
        
        # 2. 使用 context_builder 获取关系、记忆、表达习惯等
        context_data = await self._build_context_data(user_name, chat_stream, user_id)
        relation_block = context_data.get("relation_info", f"你与 {user_name} 还不太熟悉，这是早期的交流阶段。")
        memory_block = context_data.get("memory_block", "")
        expression_habits = self._build_combined_expression_block(context_data.get("expression_habits", ""))
        
        # 3. 构建活动流
        activity_stream = await self._build_activity_stream(session, user_name)
        
        # 4. 构建当前情况
        current_situation = await self._build_current_situation(
            session, user_name, situation_type, extra_context
        )
        
        # 5. 构建聊天历史总览
        chat_history_block = await self._build_chat_history_block(chat_stream)
        
        # 6. 构建可用动作
        actions_block = self._build_actions_block(available_actions)
        
        # 7. 获取规划器输出格式
        output_format = await self._get_planner_output_format()
        
        # 8. 使用统一的 prompt 管理系统格式化
        prompt = await global_prompt_manager.format_prompt(
            PROMPT_NAMES["main"],
            user_name=user_name,
            persona_block=persona_block,
            relation_block=relation_block,
            memory_block=memory_block or "（暂无相关记忆）",
            expression_habits=expression_habits or "（根据自然对话风格回复即可）",
            activity_stream=activity_stream or "（这是你们第一次聊天）",
            current_situation=current_situation,
            chat_history_block=chat_history_block,
            available_actions=actions_block,
            output_format=output_format,
        )
        
        return prompt
    
    async def build_replyer_prompt(
        self,
        session: KokoroSession,
        user_name: str,
        thought: str,
        situation_type: str = "new_message",
        chat_stream: Optional["ChatStream"] = None,
        extra_context: Optional[dict] = None,
    ) -> str:
        """
        构建回复器提示词（用于生成自然的回复文本）
        
        Args:
            session: 会话对象
            user_name: 用户名称
            thought: 规划器生成的想法
            situation_type: 情况类型
            chat_stream: 聊天流对象
            extra_context: 额外上下文
            
        Returns:
            完整的回复器提示词
        """
        extra_context = extra_context or {}
        
        # 获取 user_id
        user_id = session.user_id if session else None
        
        # 1. 构建人设块
        persona_block = self._build_persona_block()
        
        # 2. 使用 context_builder 获取关系、记忆、表达习惯等
        context_data = await self._build_context_data(user_name, chat_stream, user_id)
        relation_block = context_data.get("relation_info", f"你与 {user_name} 还不太熟悉，这是早期的交流阶段。")
        memory_block = context_data.get("memory_block", "")
        expression_habits = self._build_combined_expression_block(context_data.get("expression_habits", ""))
        
        # 3. 构建活动流
        activity_stream = await self._build_activity_stream(session, user_name)
        
        # 4. 构建当前情况（回复器专用，简化版，不包含决策语言）
        current_situation = await self._build_replyer_situation(
            session, user_name, situation_type, extra_context
        )
        
        # 5. 构建聊天历史总览
        chat_history_block = await self._build_chat_history_block(chat_stream)
        
        # 6. 构建回复情景上下文
        reply_context = await self._build_reply_context(
            session, user_name, situation_type, extra_context
        )
        
        # 7. 使用回复器专用模板
        prompt = await global_prompt_manager.format_prompt(
            PROMPT_NAMES["replyer"],
            user_name=user_name,
            persona_block=persona_block,
            relation_block=relation_block,
            memory_block=memory_block or "（暂无相关记忆）",
            activity_stream=activity_stream or "（这是你们第一次聊天）",
            current_situation=current_situation,
            chat_history_block=chat_history_block,
            expression_habits=expression_habits or "（根据自然对话风格回复即可）",
            thought=thought,
            reply_context=reply_context,
        )
        
        return prompt
    
    def _build_persona_block(self) -> str:
        """构建人设块"""
        if global_config is None:
            return "你是一个温暖、真诚的人。"
        
        personality = global_config.personality
        parts = []
        
        if personality.personality_core:
            parts.append(personality.personality_core)
        
        if personality.personality_side:
            parts.append(personality.personality_side)
        
        if personality.identity:
            parts.append(personality.identity)
        
        return "\n\n".join(parts) if parts else "你是一个温暖、真诚的人。"
    
    def _build_combined_expression_block(self, learned_habits: str) -> str:
        """
        构建合并后的表达习惯块
        
        合并：
        - 说话风格（来自人设配置 personality.reply_style）
        - 表达习惯（来自学习系统）
        """
        parts = []
        
        # 1. 添加说话风格（来自配置）
        if global_config and global_config.personality.reply_style:
            parts.append(f"**说话风格**：\n你必须参考你的说话风格：\n{global_config.personality.reply_style}")
        
        # 2. 添加学习到的表达习惯
        if learned_habits and learned_habits.strip():
            # 如果 learned_habits 已经有标题，直接追加；否则添加标题
            if learned_habits.startswith("### "):
                # 移除原有标题，统一格式
                lines = learned_habits.split("\n")
                content_lines = [l for l in lines if not l.startswith("### ")]
                parts.append("\n".join(content_lines).strip())
            else:
                parts.append(learned_habits)
        
        if parts:
            return "\n\n".join(parts)
        
        return ""
    
    async def _build_context_data(
        self,
        user_name: str,
        chat_stream: Optional["ChatStream"],
        user_id: Optional[str] = None,
    ) -> dict[str, str]:
        """
        使用 KFCContextBuilder 构建完整的上下文数据
        
        包括：关系信息、记忆、表达习惯等
        """
        if not chat_stream:
            return {
                "relation_info": f"你与 {user_name} 还不太熟悉，这是早期的交流阶段。",
                "memory_block": "",
                "expression_habits": "",
            }
        
        try:
            # 延迟导入上下文构建器
            if self._context_builder is None:
                from ..context_builder import KFCContextBuilder
                self._context_builder = KFCContextBuilder
            
            builder = self._context_builder(chat_stream)
            
            # 获取最近的消息作为 target_message（用于记忆检索）
            target_message = ""
            if chat_stream.context:
                unread = chat_stream.context.get_unread_messages()
                if unread:
                    target_message = unread[-1].processed_plain_text or unread[-1].display_message or ""
            
            context_data = await builder.build_all_context(
                sender_name=user_name,
                target_message=target_message,
                context=chat_stream.context,
                user_id=user_id,
            )
            
            return context_data
            
        except Exception as e:
            logger.warning(f"构建上下文数据失败: {e}")
            return {
                "relation_info": f"你与 {user_name} 还不太熟悉，这是早期的交流阶段。",
                "memory_block": "",
                "expression_habits": "",
            }
    
    async def _build_chat_history_block(
        self,
        chat_stream: Optional["ChatStream"],
    ) -> str:
        """
        构建聊天历史总览块
        
        从 chat_stream 获取历史消息，格式化为可读的聊天记录
        类似于 AFC 的已读历史板块
        """
        if not chat_stream:
            return "（暂无聊天记录）"
        
        try:
            from src.chat.utils.chat_message_builder import build_readable_messages_with_id
            from src.chat.utils.chat_message_builder import get_raw_msg_before_timestamp_with_chat
            from src.common.data_models.database_data_model import DatabaseMessages
            
            stream_context = chat_stream.context
            
            # 获取已读消息
            history_messages = stream_context.history_messages if stream_context else []
            
            if not history_messages:
                # 如果内存中没有历史消息，从数据库加载
                fallback_messages_dicts = await get_raw_msg_before_timestamp_with_chat(
                    chat_id=chat_stream.stream_id,
                    timestamp=time.time(),
                    limit=30,  # 限制数量，私聊不需要太多
                )
                history_messages = [
                    DatabaseMessages(**msg_dict) for msg_dict in fallback_messages_dicts
                ]
            
            if not history_messages:
                return "（暂无聊天记录）"
            
            # 过滤非文本消息（如戳一戳、禁言等系统通知）
            text_messages = self._filter_text_messages(history_messages)
            
            if not text_messages:
                return "（暂无聊天记录）"
            
            # 构建可读消息
            chat_content, _ = await build_readable_messages_with_id(
                messages=[msg.flatten() for msg in text_messages[-30:]],  # 最多30条
                timestamp_mode="normal_no_YMD",
                truncate=False,
                show_actions=False,
            )
            
            return chat_content if chat_content else "（暂无聊天记录）"
            
        except Exception as e:
            logger.warning(f"构建聊天历史块失败: {e}")
            return "（获取聊天记录失败）"
    
    def _filter_text_messages(self, messages: list) -> list:
        """
        过滤非文本消息
        
        移除系统通知消息（如戳一戳、禁言等），只保留正常的文本聊天消息
        
        Args:
            messages: 消息列表（DatabaseMessages 对象）
            
        Returns:
            过滤后的消息列表
        """
        filtered = []
        for msg in messages:
            # 跳过系统通知消息（戳一戳、禁言等）
            if getattr(msg, "is_notify", False):
                continue
            
            # 跳过没有实际文本内容的消息
            content = getattr(msg, "processed_plain_text", "") or getattr(msg, "display_message", "")
            if not content or not content.strip():
                continue
            
            filtered.append(msg)
        
        return filtered
    
    async def _build_activity_stream(
        self,
        session: KokoroSession,
        user_name: str,
    ) -> str:
        """
        构建活动流
        
        将 mental_log 中的事件按时间顺序转换为线性叙事
        使用统一的 prompt 模板
        """
        entries = session.get_recent_entries(limit=30)
        if not entries:
            return ""
        
        parts = []
        
        for entry in entries:
            part = await self._format_entry(entry, user_name)
            if part:
                parts.append(part)
        
        return "\n\n".join(parts)
    
    async def _format_entry(self, entry: MentalLogEntry, user_name: str) -> str:
        """格式化单个活动日志条目"""
        
        if entry.event_type == EventType.USER_MESSAGE:
            # 用户消息
            result = await global_prompt_manager.format_prompt(
                PROMPT_NAMES["entry_user_message"],
                time=entry.get_time_str(),
                user_name=entry.user_name or user_name,
                content=entry.content,
            )
            
            # 如果有回复状态元数据，添加说明
            reply_status = entry.metadata.get("reply_status")
            if reply_status == "in_time":
                elapsed = entry.metadata.get("elapsed_seconds", 0) / 60
                max_wait = entry.metadata.get("max_wait_seconds", 0) / 60
                result += await global_prompt_manager.format_prompt(
                    PROMPT_NAMES["entry_reply_in_time"],
                    elapsed_minutes=elapsed,
                    max_wait_minutes=max_wait,
                )
            elif reply_status == "late":
                elapsed = entry.metadata.get("elapsed_seconds", 0) / 60
                max_wait = entry.metadata.get("max_wait_seconds", 0) / 60
                result += await global_prompt_manager.format_prompt(
                    PROMPT_NAMES["entry_reply_late"],
                    elapsed_minutes=elapsed,
                    max_wait_minutes=max_wait,
                )
            
            return result
        
        elif entry.event_type == EventType.BOT_PLANNING:
            # Bot 规划
            actions_desc = self._format_actions(entry.actions)
            
            if entry.max_wait_seconds > 0:
                return await global_prompt_manager.format_prompt(
                    PROMPT_NAMES["entry_bot_planning"],
                    thought=entry.thought or "（没有特别的想法）",
                    actions_description=actions_desc,
                    expected_reaction=entry.expected_reaction or "随便怎么回应都行",
                    max_wait_minutes=entry.max_wait_seconds / 60,
                )
            else:
                return await global_prompt_manager.format_prompt(
                    PROMPT_NAMES["entry_bot_planning_no_wait"],
                    thought=entry.thought or "（没有特别的想法）",
                    actions_description=actions_desc,
                )
        
        elif entry.event_type == EventType.WAITING_UPDATE:
            # 等待中心理变化
            return await global_prompt_manager.format_prompt(
                PROMPT_NAMES["entry_waiting_update"],
                elapsed_minutes=entry.elapsed_seconds / 60,
                waiting_thought=entry.waiting_thought or "还在等...",
            )
        
        elif entry.event_type == EventType.PROACTIVE_TRIGGER:
            # 主动思考触发
            silence = entry.metadata.get("silence_duration", "一段时间")
            return await global_prompt_manager.format_prompt(
                PROMPT_NAMES["entry_proactive_trigger"],
                silence_duration=silence,
            )
        
        return ""
    
    def _format_actions(self, actions: list[dict]) -> str:
        """格式化动作列表为可读描述"""
        if not actions:
            return "（无动作）"
        
        descriptions = []
        for action in actions:
            action_type = action.get("type", "unknown")
            
            if action_type == "kfc_reply":
                content = action.get("content", "")
                if len(content) > 50:
                    content = content[:50] + "..."
                descriptions.append(f"发送消息：「{content}」")
            elif action_type == "poke_user":
                descriptions.append("戳了戳对方")
            elif action_type == "do_nothing":
                descriptions.append("什么都不做")
            elif action_type == "send_emoji":
                emoji = action.get("emoji", "")
                descriptions.append(f"发送表情：{emoji}")
            else:
                descriptions.append(f"执行动作：{action_type}")
        
        return "、".join(descriptions)
    
    async def _build_current_situation(
        self,
        session: KokoroSession,
        user_name: str,
        situation_type: str,
        extra_context: dict,
    ) -> str:
        """构建当前情况描述"""
        current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
        
        # 如果之前没有设置等待时间（max_wait_seconds == 0），视为 new_message
        if situation_type in ("reply_in_time", "reply_late"):
            max_wait = session.waiting_config.max_wait_seconds
            if max_wait <= 0:
                situation_type = "new_message"
        
        if situation_type == "new_message":
            return await global_prompt_manager.format_prompt(
                PROMPT_NAMES["situation_new_message"],
                current_time=current_time,
                user_name=user_name,
            )
        
        elif situation_type == "reply_in_time":
            elapsed = session.waiting_config.get_elapsed_seconds()
            max_wait = session.waiting_config.max_wait_seconds
            return await global_prompt_manager.format_prompt(
                PROMPT_NAMES["situation_reply_in_time"],
                current_time=current_time,
                user_name=user_name,
                elapsed_minutes=elapsed / 60,
                max_wait_minutes=max_wait / 60,
            )
        
        elif situation_type == "reply_late":
            elapsed = session.waiting_config.get_elapsed_seconds()
            max_wait = session.waiting_config.max_wait_seconds
            return await global_prompt_manager.format_prompt(
                PROMPT_NAMES["situation_reply_late"],
                current_time=current_time,
                user_name=user_name,
                elapsed_minutes=elapsed / 60,
                max_wait_minutes=max_wait / 60,
            )
        
        elif situation_type == "timeout":
            elapsed = session.waiting_config.get_elapsed_seconds()
            max_wait = session.waiting_config.max_wait_seconds
            expected = session.waiting_config.expected_reaction
            return await global_prompt_manager.format_prompt(
                PROMPT_NAMES["situation_timeout"],
                current_time=current_time,
                user_name=user_name,
                elapsed_minutes=elapsed / 60,
                max_wait_minutes=max_wait / 60,
                expected_reaction=expected or "对方能回复点什么",
            )
        
        elif situation_type == "proactive":
            silence = extra_context.get("silence_duration", "一段时间")
            trigger_reason = extra_context.get("trigger_reason", "")
            return await global_prompt_manager.format_prompt(
                PROMPT_NAMES["situation_proactive"],
                current_time=current_time,
                user_name=user_name,
                silence_duration=silence,
                trigger_reason=trigger_reason,
            )
        
        # 默认使用 new_message
        return await global_prompt_manager.format_prompt(
            PROMPT_NAMES["situation_new_message"],
            current_time=current_time,
            user_name=user_name,
        )
    
    def _build_actions_block(self, available_actions: Optional[dict]) -> str:
        """
        构建可用动作块
        
        参考 AFC planner 的格式，为每个动作展示：
        - 动作名和描述
        - 使用场景
        - JSON 示例（含参数）
        """
        if not available_actions:
            return self._get_default_actions_block()
        
        action_blocks = []
        for action_name, action_info in available_actions.items():
            block = self._format_single_action(action_name, action_info)
            if block:
                action_blocks.append(block)
        
        return "\n".join(action_blocks) if action_blocks else self._get_default_actions_block()
    
    def _format_single_action(self, action_name: str, action_info) -> str:
        """
        格式化单个动作为详细说明块
        
        Args:
            action_name: 动作名称
            action_info: ActionInfo 对象
            
        Returns:
            格式化后的动作说明
        """
        # 获取动作描述
        description = getattr(action_info, "description", "") or f"执行 {action_name}"
        
        # 获取使用场景
        action_require = getattr(action_info, "action_require", []) or []
        require_text = "\n".join(f"  - {req}" for req in action_require) if action_require else "  - 根据情况使用"
        
        # 获取参数定义
        action_parameters = getattr(action_info, "action_parameters", {}) or {}
        
        # 构建 action_data JSON 示例
        if action_parameters:
            param_lines = []
            for param_name, param_desc in action_parameters.items():
                param_lines.append(f'        "{param_name}": "<{param_desc}>"')
            action_data_json = "{\n" + ",\n".join(param_lines) + "\n      }"
        else:
            action_data_json = "{}"
        
        # 构建完整的动作块
        return f"""### {action_name}
**描述**: {description}

**使用场景**:
{require_text}

**示例**:
```json
{{
  "type": "{action_name}",
  {f'"content": "<你要说的内容>"' if action_name == "kfc_reply" else self._build_params_example(action_parameters)}
}}
```
"""
    
    def _build_params_example(self, action_parameters: dict) -> str:
        """构建参数示例字符串"""
        if not action_parameters:
            return '"_comment": "此动作无需额外参数"'
        
        parts = []
        for param_name, param_desc in action_parameters.items():
            parts.append(f'"{param_name}": "<{param_desc}>"')
        
        return ",\n  ".join(parts)
    
    def _get_default_actions_block(self) -> str:
        """获取默认的动作列表"""
        return """### kfc_reply
**描述**: 发送回复消息

**使用场景**:
  - 需要回复对方消息时使用

**示例**:
```json
{
  "type": "kfc_reply",
  "content": "你要说的话"
}
```


### do_nothing
**描述**: 什么都不做

**使用场景**:
  - 当前不需要回应时使用

**示例**:
```json
{
  "type": "do_nothing"
}
```"""
    
    async def _get_output_format(self) -> str:
        """获取输出格式模板"""
        try:
            prompt = await global_prompt_manager.get_prompt_async(
                PROMPT_NAMES["output_format"]
            )
            return prompt.template
        except KeyError:
            # 如果模板未注册，返回默认格式
            return """请用 JSON 格式回复：
{
    "thought": "你的想法",
    "actions": [{"type": "kfc_reply", "content": "你的回复"}],
    "expected_reaction": "期待的反应",
    "max_wait_seconds": 300
}"""
    
    async def _get_planner_output_format(self) -> str:
        """获取规划器输出格式模板"""
        try:
            prompt = await global_prompt_manager.get_prompt_async(
                PROMPT_NAMES["planner_output_format"]
            )
            return prompt.template
        except KeyError:
            # 如果模板未注册，返回默认格式
            return """请用 JSON 格式回复：
{
    "thought": "你的想法",
    "actions": [{"type": "kfc_reply"}],
    "expected_reaction": "期待的反应",
    "max_wait_seconds": 300
}

注意：kfc_reply 动作不需要填写 content 字段，回复内容会单独生成。"""
    
    async def _build_replyer_situation(
        self,
        session: KokoroSession,
        user_name: str,
        situation_type: str,
        extra_context: dict,
    ) -> str:
        """
        构建回复器专用的当前情况描述
        
        与 Planner 的 _build_current_situation 不同，这里不包含决策性语言，
        只描述当前的情景背景
        """
        from datetime import datetime
        current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
        
        if situation_type == "new_message":
            return f"现在是 {current_time}。{user_name} 刚给你发了消息。"
        
        elif situation_type == "reply_in_time":
            elapsed = session.waiting_config.get_elapsed_seconds()
            max_wait = session.waiting_config.max_wait_seconds
            return (
                f"现在是 {current_time}。\n"
                f"你之前发了消息后在等 {user_name} 的回复。"
                f"等了大约 {elapsed / 60:.1f} 分钟（你原本打算最多等 {max_wait / 60:.1f} 分钟）。"
                f"现在 {user_name} 回复了！"
            )
        
        elif situation_type == "reply_late":
            elapsed = session.waiting_config.get_elapsed_seconds()
            max_wait = session.waiting_config.max_wait_seconds
            return (
                f"现在是 {current_time}。\n"
                f"你之前发了消息后在等 {user_name} 的回复。"
                f"你原本打算最多等 {max_wait / 60:.1f} 分钟，但实际等了 {elapsed / 60:.1f} 分钟才收到回复。"
                f"虽然有点迟，但 {user_name} 终于回复了。"
            )
        
        elif situation_type == "timeout":
            elapsed = session.waiting_config.get_elapsed_seconds()
            max_wait = session.waiting_config.max_wait_seconds
            return (
                f"现在是 {current_time}。\n"
                f"你之前发了消息后一直在等 {user_name} 的回复。"
                f"你原本打算最多等 {max_wait / 60:.1f} 分钟，现在已经等了 {elapsed / 60:.1f} 分钟了，对方还是没回。"
                f"你决定主动说点什么。"
            )
        
        elif situation_type == "proactive":
            silence = extra_context.get("silence_duration", "一段时间")
            return (
                f"现在是 {current_time}。\n"
                f"你和 {user_name} 已经有一段时间没聊天了（沉默了 {silence}）。"
                f"你决定主动找 {user_name} 聊点什么。"
            )
        
        # 默认
        return f"现在是 {current_time}。"
    
    async def _build_reply_context(
        self,
        session: KokoroSession,
        user_name: str,
        situation_type: str,
        extra_context: dict,
    ) -> str:
        """
        构建回复情景上下文
        
        根据 situation_type 构建不同的情景描述，帮助回复器理解当前要回复的情境
        """
        # 获取最后一条用户消息
        target_message = ""
        entries = session.get_recent_entries(limit=10)
        for entry in reversed(entries):
            if entry.event_type == EventType.USER_MESSAGE:
                target_message = entry.content or ""
                break
        
        if situation_type == "new_message":
            return await global_prompt_manager.format_prompt(
                PROMPT_NAMES["replyer_context_normal"],
                user_name=user_name,
                target_message=target_message or "（无消息内容）",
            )
        
        elif situation_type == "reply_in_time":
            elapsed = session.waiting_config.get_elapsed_seconds()
            max_wait = session.waiting_config.max_wait_seconds
            return await global_prompt_manager.format_prompt(
                PROMPT_NAMES["replyer_context_in_time"],
                user_name=user_name,
                target_message=target_message or "（无消息内容）",
                elapsed_minutes=elapsed / 60,
                max_wait_minutes=max_wait / 60,
            )
        
        elif situation_type == "reply_late":
            elapsed = session.waiting_config.get_elapsed_seconds()
            max_wait = session.waiting_config.max_wait_seconds
            return await global_prompt_manager.format_prompt(
                PROMPT_NAMES["replyer_context_late"],
                user_name=user_name,
                target_message=target_message or "（无消息内容）",
                elapsed_minutes=elapsed / 60,
                max_wait_minutes=max_wait / 60,
            )
        
        elif situation_type == "proactive":
            silence = extra_context.get("silence_duration", "一段时间")
            trigger_reason = extra_context.get("trigger_reason", "")
            return await global_prompt_manager.format_prompt(
                PROMPT_NAMES["replyer_context_proactive"],
                user_name=user_name,
                silence_duration=silence,
                trigger_reason=trigger_reason,
            )
        
        # 默认使用普通情景
        return await global_prompt_manager.format_prompt(
            PROMPT_NAMES["replyer_context_normal"],
            user_name=user_name,
            target_message=target_message or "（无消息内容）",
        )


# 全局单例
_prompt_builder: Optional[PromptBuilder] = None


def get_prompt_builder() -> PromptBuilder:
    """获取全局提示词构建器"""
    global _prompt_builder
    if _prompt_builder is None:
        _prompt_builder = PromptBuilder()
    return _prompt_builder
