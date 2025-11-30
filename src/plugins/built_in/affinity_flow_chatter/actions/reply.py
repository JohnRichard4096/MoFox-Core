"""
AFC 回复动作模块

定义了两种回复相关动作：
- reply: 针对单条消息的深度回复（使用 s4u 模板）
- respond: 对未读消息的统一回应（使用 normal 模板）

这些动作是 AffinityFlowChatter 的专属动作。
"""

import asyncio
from typing import ClassVar

from src.common.data_models.database_data_model import DatabaseMessages
from src.common.logger import get_logger
from src.config.config import global_config
from src.plugin_system import ActionActivationType, BaseAction, ChatMode
from src.plugin_system.apis import generator_api, send_api

logger = get_logger("afc_reply_actions")


class ReplyAction(BaseAction):
    """Reply动作 - 针对单条消息的深度回复
    
    特点：
    - 使用 s4u (Speak for You) 模板
    - 专注于理解和回应单条消息的具体内容
    - 适合 Focus 模式下的精准回复
    - 仅限 AffinityFlowChatter 使用
    """

    # 动作基本信息
    action_name = "reply"
    action_description = "针对特定消息进行精准回复。深度理解并回应单条消息的具体内容。需要指定目标消息ID。"

    # 激活设置
    activation_type = ActionActivationType.ALWAYS  # 回复动作总是可用
    mode_enable = ChatMode.ALL  # 在所有模式下都可用
    parallel_action = False  # 回复动作不能与其他动作并行
    
    # Chatter 限制：仅允许 AffinityFlowChatter 使用
    chatter_allow: ClassVar[list[str]] = ["AffinityFlowChatter"]

    # 动作参数定义
    action_parameters: ClassVar = {
        "target_message_id": "要回复的目标消息ID（必需，来自未读消息的 <m...> 标签）",
        "content": "回复的具体内容（可选，由LLM生成）",
        "should_quote_reply": "是否引用原消息（可选，true/false，默认false。群聊中回复较早消息或需要明确指向时使用true）",
    }

    # 动作使用场景
    action_require: ClassVar = [
        "需要针对特定消息进行精准回复时使用",
        "适合单条消息的深度理解和回应",
        "必须提供准确的 target_message_id（来自未读历史的 <m...> 标签）",
        "私聊场景必须使用此动作（不支持 respond）",
        "群聊中需要明确回应某个特定用户或问题时使用",
        "关注单条消息的具体内容和上下文细节",
    ]

    # 关联类型
    associated_types: ClassVar[list[str]] = ["text"]

    async def execute(self) -> tuple[bool, str]:
        """执行reply动作 - 完整的回复流程"""
        try:
            # 确保 action_message 是 DatabaseMessages 类型，否则使用 None
            reply_message = self.action_message if isinstance(self.action_message, DatabaseMessages) else None
            
            # 检查目标消息是否为表情包
            if reply_message and getattr(reply_message, "is_emoji", False):
                if not getattr(global_config.chat, "allow_reply_to_emoji", True):
                    logger.info(f"{self.log_prefix} 目标消息为表情包且配置不允许回复，跳过")
                    return True, ""
            
            # 准备 action_data
            action_data = self.action_data.copy()
            action_data["prompt_mode"] = "s4u"
            
            # 生成回复
            success, response_set, _ = await generator_api.generate_reply(
                chat_stream=self.chat_stream,
                reply_message=reply_message,
                action_data=action_data,
                available_actions={self.action_name: self.get_action_info()},
                enable_tool=global_config.tool.enable_tool,
                request_type="chat.replyer",
                from_plugin=False,
            )
            
            if not success or not response_set:
                logger.warning(f"{self.log_prefix} 回复生成失败")
                return False, ""
            
            # 发送回复
            reply_text = await self._send_response(response_set)
            
            logger.info(f"{self.log_prefix} reply 动作执行成功")
            return True, reply_text
            
        except asyncio.CancelledError:
            logger.debug(f"{self.log_prefix} 回复任务被取消")
            return False, ""
        except Exception as e:
            logger.error(f"{self.log_prefix} reply 动作执行失败: {e}")
            import traceback
            traceback.print_exc()
            return False, ""
    
    async def _send_response(self, response_set) -> str:
        """发送回复内容"""
        reply_text = ""
        should_quote = self.action_data.get("should_quote_reply", False)
        first_sent = False
        
        # 确保 action_message 是 DatabaseMessages 类型
        reply_message = self.action_message if isinstance(self.action_message, DatabaseMessages) else None
        
        for reply_seg in response_set:
            # 处理元组格式
            if isinstance(reply_seg, tuple) and len(reply_seg) >= 2:
                _, data = reply_seg
            else:
                data = str(reply_seg)
            
            if isinstance(data, list):
                data = "".join(map(str, data))
            
            reply_text += data
            
            # 发送消息
            if not first_sent:
                await send_api.text_to_stream(
                    text=data,
                    stream_id=self.chat_stream.stream_id,
                    reply_to_message=reply_message,
                    set_reply=should_quote and bool(reply_message),
                    typing=False,
                )
                first_sent = True
            else:
                await send_api.text_to_stream(
                    text=data,
                    stream_id=self.chat_stream.stream_id,
                    reply_to_message=None,
                    set_reply=False,
                    typing=True,
                )
        
        return reply_text


class RespondAction(BaseAction):
    """Respond动作 - 对未读消息的统一回应
    
    特点：
    - 关注整体对话动态和未读消息的统一回应
    - 适合对于群聊消息下的宏观回应
    - 避免与单一用户深度对话而忽略其他用户的消息
    - 仅限 AffinityFlowChatter 使用
    """

    # 动作基本信息
    action_name = "respond"
    action_description = "统一回应所有未读消息。理解整体对话动态和话题走向，生成连贯的回复。无需指定目标消息。"

    # 激活设置
    activation_type = ActionActivationType.ALWAYS  # 回应动作总是可用
    mode_enable = ChatMode.ALL  # 在所有模式下都可用
    parallel_action = False  # 回应动作不能与其他动作并行
    
    # Chatter 限制：仅允许 AffinityFlowChatter 使用
    chatter_allow: ClassVar[list[str]] = ["AffinityFlowChatter"]

    # 动作参数定义
    action_parameters: ClassVar = {
        "content": "回复的具体内容（可选，由LLM生成）",
    }

    # 动作使用场景
    action_require: ClassVar = [
        "需要统一回应多条未读消息时使用（Normal 模式专用）",
        "适合理解整体对话动态而非单条消息",
        "不需要指定 target_message_id，会自动处理所有未读消息",
        "关注对话流程、话题走向和整体氛围",
        "适合群聊中的自然对话流，无需精确指向特定消息",
        "可以同时回应多个话题或参与者",
    ]

    # 关联类型
    associated_types: ClassVar[list[str]] = ["text"]

    async def execute(self) -> tuple[bool, str]:
        """执行respond动作 - 完整的回复流程"""
        try:
            # 准备 action_data
            action_data = self.action_data.copy()
            action_data["prompt_mode"] = "normal"
            
            # 确保 action_message 是 DatabaseMessages 类型，否则使用 None
            reply_message = self.action_message if isinstance(self.action_message, DatabaseMessages) else None
            
            # 生成回复
            success, response_set, _ = await generator_api.generate_reply(
                chat_stream=self.chat_stream,
                reply_message=reply_message,
                action_data=action_data,
                available_actions={self.action_name: self.get_action_info()},
                enable_tool=global_config.tool.enable_tool,
                request_type="chat.replyer",
                from_plugin=False,
            )
            
            if not success or not response_set:
                logger.warning(f"{self.log_prefix} 回复生成失败")
                return False, ""
            
            # 发送回复（respond 默认不引用）
            reply_text = await self._send_response(response_set)
            
            logger.info(f"{self.log_prefix} respond 动作执行成功")
            return True, reply_text
            
        except asyncio.CancelledError:
            logger.debug(f"{self.log_prefix} 回复任务被取消")
            return False, ""
        except Exception as e:
            logger.error(f"{self.log_prefix} respond 动作执行失败: {e}")
            import traceback
            traceback.print_exc()
            return False, ""
    
    async def _send_response(self, response_set) -> str:
        """发送回复内容（不引用原消息）"""
        reply_text = ""
        first_sent = False
        
        for reply_seg in response_set:
            if isinstance(reply_seg, tuple) and len(reply_seg) >= 2:
                _, data = reply_seg
            else:
                data = str(reply_seg)
            
            if isinstance(data, list):
                data = "".join(map(str, data))
            
            reply_text += data
            
            if not first_sent:
                await send_api.text_to_stream(
                    text=data,
                    stream_id=self.chat_stream.stream_id,
                    reply_to_message=None,
                    set_reply=False,
                    typing=False,
                )
                first_sent = True
            else:
                await send_api.text_to_stream(
                    text=data,
                    stream_id=self.chat_stream.stream_id,
                    reply_to_message=None,
                    set_reply=False,
                    typing=True,
                )
        
        return reply_text
