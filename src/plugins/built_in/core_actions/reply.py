from typing import Tuple

# 导入新插件系统
from src.plugin_system import BaseAction, ActionActivationType, ChatMode

# 导入依赖的系统组件
from src.common.logger import get_logger
from src.plugin_system.apis import generator_api


logger = get_logger("reply_action")


class ReplyAction(BaseAction):
    """基本回复动作:确保系统始终有一个可用的回退动作!!!"""

    focus_activation_type = ActionActivationType.ALWAYS
    normal_activation_type = ActionActivationType.ALWAYS
    mode_enable = ChatMode.ALL
    parallel_action = False

    # 动作基本信息
    action_name = "reply"
    action_description = "进行基本回复"

    # 动作参数定义
    action_parameters = {}

    # 动作使用场景
    action_require = [""]

    # 关联类型
    associated_types = []

    async def execute(self) -> Tuple[bool, str]:
        """执行回复动作"""
        try:
            reason = self.action_data.get("reason", "")
            
            logger.info(f"{self.log_prefix} 执行基本回复动作，原因: {reason}")

            # 获取当前消息和上下文
            if not self.chat_stream or not self.chat_stream.get_latest_message():
                logger.warning(f"{self.log_prefix} 没有可回复的消息")
                return False, ""

            latest_message = self.chat_stream.get_latest_message()
            
            # 使用生成器API生成回复
            success, reply_set, _ = await generator_api.generate_reply(
                target_message=latest_message.processed_plain_text,
                chat_stream=self.chat_stream,
                reasoning=reason,
                action_message={}
            )
            
            if success and reply_set:
                # 提取回复文本
                reply_text = ""
                for message_type, content in reply_set:
                    if message_type == "text":
                        reply_text += content
                        break
                
                if reply_text:
                    logger.info(f"{self.log_prefix} 回复生成成功: {reply_text[:50]}...")
                    return True, reply_text
                else:
                    logger.warning(f"{self.log_prefix} 生成的回复为空")
                    return False, ""
            else:
                logger.warning(f"{self.log_prefix} 回复生成失败")
                return False, ""

        except Exception as e:
            logger.error(f"{self.log_prefix} 执行回复动作时发生异常: {e}")
            import traceback
            traceback.print_exc()
            return False, ""
