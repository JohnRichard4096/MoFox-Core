import asyncio
from datetime import datetime
from typing import List, Tuple, Type, Optional
from dateutil.parser import parse as parse_datetime

from src.common.logger import get_logger
from src.manager.async_task_manager import AsyncTask, async_task_manager
from src.person_info.person_info import get_person_info_manager
from src.plugin_system import (
    BaseAction,
    ActionInfo,
    BasePlugin,
    register_plugin,
    ActionActivationType,
)
from src.plugin_system.apis import send_api, llm_api
from src.plugin_system.base.component_types import ChatType, ComponentType

logger = get_logger(__name__)


# ============================ AsyncTask ============================

class ReminderTask(AsyncTask):
    def __init__(self, delay: float, stream_id: str, group_id: Optional[str], is_group: bool, target_user_id: str, target_user_name: str, event_details: str, creator_name: str):
        super().__init__(task_name=f"ReminderTask_{target_user_id}_{datetime.now().timestamp()}")
        self.delay = delay
        self.stream_id = stream_id
        self.group_id = group_id
        self.is_group = is_group
        self.target_user_id = target_user_id
        self.target_user_name = target_user_name
        self.event_details = event_details
        self.creator_name = creator_name

    async def run(self):
        try:
            if self.delay > 0:
                logger.info(f"等待 {self.delay:.2f} 秒后执行提醒...")
                await asyncio.sleep(self.delay)
            
            logger.info(f"执行提醒任务: 给 {self.target_user_name} 发送关于 '{self.event_details}' 的提醒")

            reminder_text = f"叮咚！这是 {self.creator_name} 让我准时提醒你的事情：\n\n{self.event_details}"

            if self.is_group:
                # 在群聊中，构造 @ 消息段并发送
                message_payload = [
                    {"type": "at", "data": {"qq": self.target_user_id}},
                    {"type": "text", "data": {"text": f" {reminder_text}"}}
                ]
                await send_api.adapter_command_to_stream(
                    action="send_group_msg",
                    params={"group_id": self.group_id, "message": message_payload},
                    stream_id=self.stream_id
                )
            else:
                # 在私聊中，直接发送文本
                await send_api.text_to_stream(text=reminder_text, stream_id=self.stream_id)

            logger.info(f"提醒任务 {self.task_name} 成功完成。")

        except Exception as e:
            logger.error(f"执行提醒任务 {self.task_name} 时出错: {e}", exc_info=True)


# =============================== Actions ===============================

class RemindAction(BaseAction):
    """一个能从对话中智能识别并设置定时提醒的动作。"""

    # === 基本信息 ===
    action_name = "set_reminder"
    action_description = "根据用户的对话内容，智能地设置一个未来的提醒事项。"
    
    @staticmethod
    def get_action_info() -> ActionInfo:
        return ActionInfo(
            name="set_reminder",
            component_type=ComponentType.ACTION,
            activation_type=ActionActivationType.KEYWORD,
            activation_keywords=["提醒", "叫我", "记得", "别忘了"]
        )

    # === LLM 判断与参数提取 ===
    llm_judge_prompt = ""
    action_parameters = {}
    action_require = [
        "当用户请求在未来的某个时间点提醒他/她或别人某件事时使用",
        "适用于包含明确时间信息和事件描述的对话",
        "例如：'10分钟后提醒我收快递'、'明天早上九点喊一下李四参加晨会'"
    ]

    async def execute(self) -> Tuple[bool, str]:
        """执行设置提醒的动作"""
        try:
            # 获取所有可用的模型配置
            available_models = llm_api.get_available_models()
            if "planner" not in available_models:
                raise ValueError("未找到 'planner' 决策模型配置，无法解析时间")
            model_to_use = available_models["planner"]

            prompt = f"""
            从以下用户输入中提取提醒事件的关键信息。
            用户输入: "{self.chat_stream.context.message.processed_plain_text}"

            请以JSON格式返回提取的信息，包含以下字段:
            - "user_name": 需要被提醒的人的姓名。如果未指定，则默认为"自己"。
            - "remind_time": 描述提醒时间的自然语言字符串。
            - "event_details": 需要提醒的具体事件内容。

            如果无法提取完整信息，请返回一个包含空字符串的JSON对象，例如：{{"user_name": "", "remind_time": "", "event_details": ""}}
            """

            success, response, _, _ = await llm_api.generate_with_model(
                prompt,
                model_config=model_to_use,
                request_type="plugin.reminder.parameter_extractor"
            )

            if not success or not response:
                raise ValueError(f"LLM未能返回有效的参数: {response}")

            import json
            import re
            try:
                # 提取JSON部分
                json_match = re.search(r"\{.*\}", response, re.DOTALL)
                if not json_match:
                    raise ValueError("LLM返回的内容中不包含JSON")
                action_data = json.loads(json_match.group(0))
            except json.JSONDecodeError:
                logger.error(f"[ReminderPlugin] LLM返回的不是有效的JSON: {response}")
                return False, "LLM返回的不是有效的JSON"
            user_name = action_data.get("user_name")
            remind_time_str = action_data.get("remind_time")
            event_details = action_data.get("event_details")

        except Exception as e:
            logger.error(f"[ReminderPlugin] 解析参数时出错: {e}", exc_info=True)
            return False, "解析参数时出错"

        if not all([user_name, remind_time_str, event_details]):
            missing_params = [p for p, v in {"user_name": user_name, "remind_time": remind_time_str, "event_details": event_details}.items() if not v]
            error_msg = f"缺少必要的提醒参数: {', '.join(missing_params)}"
            logger.warning(f"[ReminderPlugin] LLM未能提取完整参数: {error_msg}")
            return False, error_msg

        # 1. 解析时间
        try:
            assert isinstance(remind_time_str, str)
            # 优先尝试直接解析
            try:
                target_time = parse_datetime(remind_time_str, fuzzy=True)
            except Exception:
                # 如果直接解析失败，调用 LLM 进行转换
                logger.info(f"[ReminderPlugin] 直接解析时间 '{remind_time_str}' 失败，尝试使用 LLM 进行转换...")
                
                # 获取所有可用的模型配置
                available_models = llm_api.get_available_models()
                if "planner" not in available_models:
                    raise ValueError("未找到 'planner' 决策模型配置，无法解析时间")
                
                # 明确使用 'planner' 模型
                model_to_use = available_models["planner"]

                # 在执行时动态获取当前时间
                current_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                prompt = (
                    f"请将以下自然语言时间短语转换为一个未来的、标准的 'YYYY-MM-DD HH:MM:SS' 格式。"
                    f"请只输出转换后的时间字符串，不要包含任何其他说明或文字。\n"
                    f"作为参考，当前时间是: {current_time_str}\n"
                    f"需要转换的时间短语是: '{remind_time_str}'"
                )
                
                success, response, _, _ = await llm_api.generate_with_model(
                    prompt, 
                    model_config=model_to_use,
                    request_type="plugin.reminder.time_parser"
                )
                
                if not success or not response:
                    raise ValueError(f"LLM未能返回有效的时间字符串: {response}")

                converted_time_str = response.strip()
                logger.info(f"[ReminderPlugin] LLM 转换结果: '{converted_time_str}'")
                target_time = parse_datetime(converted_time_str, fuzzy=False)

        except Exception as e:
            logger.error(f"[ReminderPlugin] 无法解析或转换时间字符串 '{remind_time_str}': {e}", exc_info=True)
            await self.send_text(f"抱歉，我无法理解您说的时间 '{remind_time_str}'，提醒设置失败。")
            return False, f"无法解析时间 '{remind_time_str}'"

        now = datetime.now()
        if target_time <= now:
            await self.send_text("提醒时间必须是一个未来的时间点哦，提醒设置失败。")
            return False, "提醒时间必须在未来"

        delay_seconds = (target_time - now).total_seconds()

        # 2. 解析用户
        person_manager = get_person_info_manager()
        user_id_to_remind = None
        user_name_to_remind = ""
        
        assert isinstance(user_name, str)
        
        if user_name.strip() in ["自己", "我", "me"]:
            user_id_to_remind = self.user_id
            user_name_to_remind = self.user_nickname
        else:
            user_info = await person_manager.get_person_info_by_name(user_name)
            if not user_info or not user_info.get("user_id"):
                logger.warning(f"[ReminderPlugin] 找不到名为 '{user_name}' 的用户")
                await self.send_text(f"抱歉，我的联系人里找不到叫做 '{user_name}' 的人，提醒设置失败。")
                return False, f"用户 '{user_name}' 不存在"
            user_id_to_remind = user_info.get("user_id")
            user_name_to_remind = user_name

        # 3. 创建并调度异步任务
        try:
            assert user_id_to_remind is not None
            assert event_details is not None
            
            reminder_task = ReminderTask(
                delay=delay_seconds,
                stream_id=self.chat_stream.stream_id,
                group_id=self.chat_stream.group_info.group_id if self.is_group and self.chat_stream.group_info else None,
                is_group=self.is_group,
                target_user_id=str(user_id_to_remind),
                target_user_name=str(user_name_to_remind),
                event_details=str(event_details),
                creator_name=str(self.user_nickname)
            )
            await async_task_manager.add_task(reminder_task)
            
            # 4. 发送确认消息
            confirm_message = f"好的，我记下了。\n将在 {target_time.strftime('%Y-%m-%d %H:%M:%S')} 提醒 {user_name_to_remind}：\n{event_details}"
            await self.send_text(confirm_message)
            
            return True, "提醒设置成功"
        except Exception as e:
            logger.error(f"[ReminderPlugin] 创建提醒任务时出错: {e}", exc_info=True)
            await self.send_text("抱歉，设置提醒时发生了一点内部错误。")
            return False, "设置提醒时发生内部错误"


# =============================== Plugin ===============================

@register_plugin
class ReminderPlugin(BasePlugin):
    """一个能从对话中智能识别并设置定时提醒的插件。"""

    # --- 插件基础信息 ---
    plugin_name = "reminder_plugin"
    enable_plugin = True
    dependencies = []
    python_dependencies = []
    config_file_name = "config.toml"
    config_schema = {}

    def get_plugin_components(self) -> List[Tuple[ActionInfo, Type[BaseAction]]]:
        """注册插件的所有功能组件。"""
        return [
            (RemindAction.get_action_info(), RemindAction)
        ]
