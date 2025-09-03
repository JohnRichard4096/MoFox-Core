import time
import random
import traceback
from typing import Optional, Dict, Any, Tuple

from src.common.logger import get_logger
from src.config.config import global_config
from src.plugin_system.apis import generator_api, send_api, message_api, database_api
from src.person_info.person_info import get_person_info_manager
from .hfc_context import HfcContext

# 导入反注入系统
from src.chat.antipromptinjector import get_anti_injector
from src.chat.antipromptinjector.types import ProcessResult
from src.chat.utils.prompt_builder import Prompt

logger = get_logger("hfc")
anti_injector_logger = get_logger("anti_injector")


class ResponseHandler:
    def __init__(self, context: HfcContext):
        """
        初始化响应处理器

        Args:
            context: HFC聊天上下文对象

        功能说明:
        - 负责生成和发送机器人的回复
        - 处理回复的格式化和发送逻辑
        - 管理回复状态和日志记录
        """
        self.context = context

    async def generate_and_send_reply(
        self,
        response_set,
        reply_to_str,
        loop_start_time,
        action_message,
        cycle_timers: Dict[str, float],
        thinking_id,
        plan_result,
    ) -> Tuple[Dict[str, Any], str, Dict[str, float]]:
        """
        生成并发送回复的主方法

        Args:
            response_set: 生成的回复内容集合
            reply_to_str: 回复目标字符串
            loop_start_time: 循环开始时间
            action_message: 动作消息数据
            cycle_timers: 循环计时器
            thinking_id: 思考ID
            plan_result: 规划结果

        Returns:
            tuple: (循环信息, 回复文本, 计时器信息)

        功能说明:
        - 发送生成的回复内容
        - 存储动作信息到数据库
        - 构建并返回完整的循环信息
        - 用于上级方法的状态跟踪
        """
        reply_text = await self.send_response(response_set, reply_to_str, loop_start_time, action_message)

        person_info_manager = get_person_info_manager()

        platform = "default"
        if self.context.chat_stream:
            platform = (
                action_message.get("chat_info_platform")
                or action_message.get("user_platform")
                or self.context.chat_stream.platform
            )

        user_id = action_message.get("user_id", "")
        person_id = person_info_manager.get_person_id(platform, user_id)
        person_name = await person_info_manager.get_value(person_id, "person_name")
        action_prompt_display = f"你对{person_name}进行了回复：{reply_text}"

        await database_api.store_action_info(
            chat_stream=self.context.chat_stream,
            action_build_into_prompt=False,
            action_prompt_display=action_prompt_display,
            action_done=True,
            thinking_id=thinking_id,
            action_data={"reply_text": reply_text, "reply_to": reply_to_str},
            action_name="reply",
        )

        loop_info: Dict[str, Any] = {
            "loop_plan_info": {
                "action_result": plan_result.get("action_result", {}),
            },
            "loop_action_info": {
                "action_taken": True,
                "reply_text": reply_text,
                "command": "",
                "taken_time": time.time(),
            },
        }

        return loop_info, reply_text, cycle_timers

    async def send_response(self, reply_set, thinking_start_time, message_data) -> str:
        """
        发送回复内容的具体实现

        Args:
            reply_set: 回复内容集合，包含多个回复段
            reply_to: 回复目标
            thinking_start_time: 思考开始时间
            message_data: 消息数据

        Returns:
            str: 完整的回复文本

        功能说明:
        - 检查是否有新消息需要回复
        - 处理主动思考的"沉默"决定
        - 根据消息数量决定是否添加回复引用
        - 逐段发送回复内容，支持打字效果
        - 正确处理元组格式的回复段
        """
        current_time = time.time()
        new_message_count = message_api.count_new_messages(
            chat_id=self.context.stream_id, start_time=thinking_start_time, end_time=current_time
        )

        need_reply = new_message_count >= random.randint(2, 4)

        reply_text = ""
        is_proactive_thinking = message_data.get("message_type") == "proactive_thinking"

        first_replied = False
        for reply_seg in reply_set:
            # 调试日志：验证reply_seg的格式
            logger.debug(f"Processing reply_seg type: {type(reply_seg)}, content: {reply_seg}")

            # 修正：正确处理元组格式 (格式为: (type, content))
            if isinstance(reply_seg, tuple) and len(reply_seg) >= 2:
                _, data = reply_seg
            else:
                # 向下兼容：如果已经是字符串，则直接使用
                data = str(reply_seg)

            reply_text += data

            if is_proactive_thinking and data.strip() == "沉默":
                logger.info(f"{self.context.log_prefix} 主动思考决定保持沉默，不发送消息")
                continue

            if not first_replied:
                await send_api.text_to_stream(
                    text=data,
                    stream_id=self.context.stream_id,
                    reply_to_message = message_data,
                    set_reply=need_reply,
                    typing=False,
                )
                first_replied = True
            else:
                await send_api.text_to_stream(
                    text=data,
                    stream_id=self.context.stream_id,
                    reply_to_message = message_data,
                    set_reply=need_reply,
                    typing=True,
                )

        return reply_text

    # TODO: 已废弃
    async def generate_response(
        self,
        message_data: dict,
        available_actions: Optional[Dict[str, Any]],
        reply_to: str,
        request_type: str = "chat.replyer.normal",
    ) -> Optional[list]:
        """
        生成回复内容

        Args:
            message_data: 消息数据
            available_actions: 可用动作列表
            reply_to: 回复目标
            request_type: 请求类型，默认为普通回复

        Returns:
            list: 生成的回复内容列表，失败时返回None

        功能说明:
        - 在生成回复前进行反注入检测（提高效率）
        - 调用生成器API生成回复
        - 根据配置启用或禁用工具功能
        - 处理生成失败的情况
        - 记录生成过程中的错误和异常
        """
        try:
            # === 反注入检测（仅在需要生成回复时） ===
            # 执行反注入检测（直接使用字典格式）
            anti_injector = get_anti_injector()
            result, modified_content, reason = await anti_injector.process_message(
                message_data, self.context.chat_stream
            )

            # 根据反注入结果处理消息数据
            await anti_injector.handle_message_storage(result, modified_content, reason, message_data)

            if result == ProcessResult.BLOCKED_BAN:
                # 用户被封禁 - 直接阻止回复生成
                anti_injector_logger.warning(f"用户被反注入系统封禁，阻止回复生成: {reason}")
                return None
            elif result == ProcessResult.BLOCKED_INJECTION:
                # 消息被阻止（危险内容等） - 直接阻止回复生成
                anti_injector_logger.warning(f"消息被反注入系统阻止，阻止回复生成: {reason}")
                return None
            elif result == ProcessResult.COUNTER_ATTACK:
                # 反击模式：生成反击消息作为回复
                anti_injector_logger.info(f"反击模式启动，生成反击回复: {reason}")
                if modified_content:
                    # 返回反击消息作为回复内容
                    return [("text", modified_content)]
                else:
                    # 没有反击内容时阻止回复生成
                    return None

            # 检查是否需要加盾处理
            safety_prompt = None
            if result == ProcessResult.SHIELDED:
                # 获取安全系统提示词并注入
                shield = anti_injector.shield
                safety_prompt = shield.get_safety_system_prompt()
                await Prompt.create_async(safety_prompt, "anti_injection_safety_prompt")
                anti_injector_logger.info(f"消息已被反注入系统加盾处理，已注入安全提示词: {reason}")

            # 处理被修改的消息内容（用于生成回复）
            modified_reply_to = reply_to
            if modified_content:
                # 更新消息内容用于生成回复
                anti_injector_logger.info(f"消息内容已被反注入系统修改，使用修改后内容生成回复: {reason}")
                # 解析原始reply_to格式："发送者:消息内容"
                if ":" in reply_to:
                    sender_part, _ = reply_to.split(":", 1)
                    modified_reply_to = f"{sender_part}:{modified_content}"
                else:
                    # 如果格式不标准，直接使用修改后的内容
                    modified_reply_to = modified_content

            # === 正常的回复生成流程 ===
            success, reply_set, _ = await generator_api.generate_reply(
                chat_stream=self.context.chat_stream,
                reply_to=modified_reply_to,  # 使用可能被修改的内容
                available_actions=available_actions,
                enable_tool=global_config.tool.enable_tool,
                request_type=request_type,
                from_plugin=False,
            )

            if not success or not reply_set:
                logger.info(f"对 {message_data.get('processed_plain_text')} 的回复生成失败")
                return None

            return reply_set

        except Exception as e:
            logger.error(f"{self.context.log_prefix}回复生成出现错误：{str(e)} {traceback.format_exc()}")
            return None
