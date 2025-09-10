from typing import List, Tuple, Type
from src.plugin_system import (
    BasePlugin,
    BaseCommand,
    CommandInfo,
    register_plugin,
    BaseAction,
    ActionInfo,
    ActionActivationType,
)
from src.person_info.person_info import get_person_info_manager
from src.common.logger import get_logger
from src.plugin_system.base.component_types import ChatType

logger = get_logger(__name__)


class AtAction(BaseAction):
    """发送艾特消息"""

    # === 基本信息（必须填写）===
    action_name = "at_user"
    action_description = "发送艾特消息"
    activation_type = ActionActivationType.LLM_JUDGE 
    parallel_action = False
    chat_type_allow = ChatType.GROUP

    # === 功能描述（必须填写）===
    action_parameters = {"user_name": "需要艾特用户的名字", "at_message": "艾特用户时要发送的消息"}
    action_require = [
        "当需要艾特某个用户时使用",
        "当你需要提醒特定用户查看消息时使用",
        "在回复中需要明确指向某个用户时使用",
    ]
    llm_judge_prompt = """
    判定是否需要使用艾特用户动作的条件：
    1. 你在对话中提到了某个具体的人，并且需要提醒他/她。
    3. 上下文明确需要你艾特一个或多个人。

    请回答"是"或"否"。
    """
    associated_types = ["text"]

    async def execute(self) -> Tuple[bool, str]:
        """执行艾特用户的动作"""
        user_name = self.action_data.get("user_name")
        at_message = self.action_data.get("at_message")

        if not user_name or not at_message:
            logger.warning("艾特用户的动作缺少必要参数。")
            return False, "缺少必要参数"

        from src.plugin_system.apis import send_api
        from fuzzywuzzy import process

        group_id = self.chat_stream.group_info.group_id
        if not group_id:
            return False, "无法获取群组ID"

        response = await send_api.adapter_command_to_stream(
            action="get_group_member_list",
            params={"group_id": group_id},
            stream_id=self.chat_id,
        )

        if response.get("status") != "ok":
            return False, f"获取群成员列表失败: {response.get('message')}"

        member_list = response.get("data", [])
        if not member_list:
            return False, "群成员列表为空"

        # 优化用户匹配逻辑
        best_match = None
        user_id = None

        # 1. 完全精确匹配
        for member in member_list:
            card = member.get("card", "")
            nickname = member.get("nickname", "")
            if user_name == card or user_name == nickname:
                best_match = card if user_name == card else nickname
                user_id = member["user_id"]
                logger.info(f"找到完全精确匹配: '{user_name}' -> '{best_match}' (ID: {user_id})")
                break
        
        # 2. 包含关系匹配
        if not best_match:
            containing_matches = []
            for member in member_list:
                card = member.get("card", "")
                nickname = member.get("nickname", "")
                if user_name in card:
                    containing_matches.append((card, member["user_id"]))
                elif user_name in nickname:
                    containing_matches.append((nickname, member["user_id"]))
            
            if containing_matches:
                # 选择最短的匹配项，因为通常更精确
                best_match, user_id = min(containing_matches, key=lambda x: len(x[0]))
                logger.info(f"找到包含关系匹配: '{user_name}' -> '{best_match}' (ID: {user_id})")

        # 3. 模糊匹配作为兜底
        if not best_match:
            choices = {member["card"] or member["nickname"]: member["user_id"] for member in member_list}
            fuzzy_match, score = process.extractOne(user_name, choices.keys())
            if score >= 60: # 维持较高的阈值
                best_match = fuzzy_match
                user_id = choices[best_match]
                logger.info(f"找到模糊匹配: '{user_name}' -> '{best_match}' (ID: {user_id}, Score: {score})")
        
        if not best_match:
            logger.warning(f"所有匹配策略都未能找到用户: '{user_name}'")
            return False, "用户不存在"
        
        user_info = {"user_id": user_id, "user_nickname": best_match}

        try:
            from src.chat.replyer.default_generator import DefaultReplyer
            from src.chat.message_receive.chat_stream import get_chat_manager

            chat_manager = get_chat_manager()
            chat_stream = chat_manager.get_stream(self.chat_id)
            
            if not chat_stream:
                logger.error(f"找不到聊天流: {self.stream_id}")
                return False, "聊天流不存在"
            
            replyer = DefaultReplyer(chat_stream)
            # 优化提示词，消除记忆割裂感
            reminder_task = at_message.replace("定时提醒：", "").strip()
            extra_info = f"""你之前记下了一个提醒任务：'{reminder_task}'
现在时间到了，你需要去提醒用户 '{user_name}'。

**重要规则**：
- 你的任务**只**是生成提醒的**内容**。
- **绝对不要**在你的回复中包含任何`@`符号或者目标用户的名字。真正的@操作会由系统自动完成。
- 像一个朋友一样，自然地完成这个提醒，而不是生硬地复述任务。

请直接输出提醒的**内容**。"""

            success, llm_response, _ = await replyer.generate_reply_with_context(
                reply_to=f"是时候提醒'{user_name}'了",  # 内部上下文，更符合执行任务的语境
                extra_info=extra_info,
                enable_tool=False,
                from_plugin=True  # 标记为插件调用，以便LLM更好地理解上下文
            )
            
            if not success or not llm_response:
                logger.error("回复器生成回复失败")
                return False, "回复生成失败"
            
            final_message = llm_response.get("content", "")
            if not final_message:
                logger.warning("回复器生成了空内容")
                return False, "回复内容为空"

            await self.send_command(
                "SEND_AT_MESSAGE",
                args={"group_id": self.chat_stream.group_info.group_id, "qq_id": user_id, "text": final_message},
                display_message=f"艾特用户 {user_name} 并发送消息: {final_message}",
            )
            
            await self.store_action_info(
                action_build_into_prompt=True,
                action_prompt_display=f"执行了艾特用户动作：艾特用户 {user_name} 并发送消息: {final_message}",
                action_done=True,
            )
            
            logger.info(f"成功发送艾特消息给 {user_name}: {final_message}")
            return True, "艾特消息发送成功"
                
        except Exception as e:
            logger.error(f"执行艾特用户动作时发生异常: {e}", exc_info=True)
            return False, f"执行失败: {str(e)}"


@register_plugin
class AtUserPlugin(BasePlugin):
    plugin_name: str = "at_user_plugin"
    enable_plugin: bool = True
    dependencies: list[str] = []
    python_dependencies: list[str] = ["fuzzywuzzy", "python-Levenshtein"]
    config_file_name: str = "config.toml"
    config_schema: dict = {}

    def get_plugin_components(self) -> List[Tuple[CommandInfo | ActionInfo, Type[BaseCommand] | Type[BaseAction]]]:
        return [
            (AtAction.get_action_info(), AtAction),
        ]
