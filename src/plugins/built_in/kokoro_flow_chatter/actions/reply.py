"""
KFC 回复动作模块

KFC 的 reply 动作与 AFC 不同：
- 不调用 LLM 生成回复，content 由 Replyer 提前生成
- 动作本身只负责发送 content 参数中的内容
"""

from typing import ClassVar

from src.common.logger import get_logger
from src.plugin_system import ActionActivationType, BaseAction, ChatMode
from src.plugin_system.apis import send_api

logger = get_logger("kfc_reply_action")


class KFCReplyAction(BaseAction):
    """KFC Reply 动作 - 发送已生成的回复内容

    特点：
    - 不调用 LLM，直接发送 content 参数中的内容
    - content 由 Replyer 提前生成
    - 仅限 KokoroFlowChatter 使用

    注意：使用 kfc_reply 作为动作名称以避免与 AFC 的 reply 动作冲突
    """

    # 动作基本信息
    action_name = "kfc_reply"
    action_description = "发送回复消息。content 参数包含要发送的内容。"

    # 激活设置
    activation_type = ActionActivationType.ALWAYS
    mode_enable = ChatMode.ALL
    parallel_action = False
    
    # Chatter 限制：仅允许 KokoroFlowChatter 使用
    chatter_allow: ClassVar[list[str]] = ["KokoroFlowChatter"]

    # 动作参数定义
    action_parameters: ClassVar = {
        "content": "要发送的回复内容（必需，由 Replyer 生成）",
        "should_quote_reply": "是否引用原消息（可选，true/false，默认 false）",
    }

    # 动作使用场景
    action_require: ClassVar = [
        "发送回复消息时使用",
        "content 参数必须包含要发送的内容",
    ]

    # 关联类型
    associated_types: ClassVar[list[str]] = ["text"]

    async def execute(self) -> tuple[bool, str]:
        """执行 reply 动作 - 发送 content 中的内容"""
        try:
            # 获取要发送的内容
            content = self.action_data.get("content", "")
            if not content:
                logger.warning(f"{self.log_prefix} content 为空，跳过发送")
                return True, ""
            
            # 获取是否引用
            should_quote = self.action_data.get("should_quote_reply", False)
            
            # 发送消息
            await send_api.text_to_stream(
                text=content,
                stream_id=self.chat_stream.stream_id,
                reply_to_message=self.action_message,
                set_reply=should_quote and bool(self.action_message),
                typing=False,
            )
            
            logger.info(f"{self.log_prefix} KFC reply 动作执行成功")
            return True, content
            
        except Exception as e:
            logger.error(f"{self.log_prefix} KFC reply 动作执行失败: {e}")
            import traceback
            traceback.print_exc()
            return False, ""
