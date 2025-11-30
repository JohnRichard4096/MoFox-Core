import asyncio
import traceback
from typing import Any, TYPE_CHECKING

from src.chat.message_receive.chat_stream import get_chat_manager
from src.common.data_models.database_data_model import DatabaseMessages
from src.common.logger import get_logger
from src.plugin_system.base.base_action import BaseAction
from src.plugin_system.base.component_types import ActionInfo, ComponentType
from src.plugin_system.core.component_registry import component_registry

if TYPE_CHECKING:
    from src.chat.message_receive.chat_stream import ChatStream

logger = get_logger("action_manager")


class ChatterActionManager:
    """
    动作管理器，用于管理和执行动作
    
    职责：
    - 加载和管理可用动作集
    - 创建动作实例
    - 执行动作（所有动作逻辑在 Action.execute() 中实现）
    """

    def __init__(self):
        """初始化动作管理器"""
        self._using_actions: dict[str, ActionInfo] = {}
        self.chat_id: str | None = None
        self.log_prefix: str = "ChatterActionManager"

    async def load_actions(self, stream_id: str | None):
        """根据 stream_id 加载当前可用的动作"""
        self.chat_id = stream_id
        self._using_actions = component_registry.get_default_actions(stream_id)
        logger.debug(f"已为 stream '{stream_id}' 加载 {len(self._using_actions)} 个可用动作: {list(self._using_actions.keys())}")

    @staticmethod
    def create_action(
        action_name: str,
        action_data: dict,
        reasoning: str,
        cycle_timers: dict,
        thinking_id: str,
        chat_stream: "ChatStream",
        log_prefix: str,
        shutting_down: bool = False,
        action_message: DatabaseMessages | None = None,
    ) -> BaseAction | None:
        """
        创建动作处理器实例

        Args:
            action_name: 动作名称
            action_data: 动作数据
            reasoning: 执行理由
            cycle_timers: 计时器字典
            thinking_id: 思考ID
            chat_stream: 聊天流
            log_prefix: 日志前缀
            shutting_down: 是否正在关闭
            action_message: 目标消息

        Returns:
            BaseAction | None: 创建的动作处理器实例
        """
        try:
            # 获取组件类
            component_class: type[BaseAction] = component_registry.get_component_class(
                action_name, ComponentType.ACTION
            )  # type: ignore
            if not component_class:
                logger.warning(f"{log_prefix} 未找到Action组件: {action_name}")
                return None

            # 获取组件信息
            component_info = component_registry.get_component_info(action_name, ComponentType.ACTION)
            if not component_info:
                logger.warning(f"{log_prefix} 未找到Action组件信息: {action_name}")
                return None

            # 获取插件配置
            plugin_config = component_registry.get_plugin_config(component_info.plugin_name)

            # 创建动作实例
            instance = component_class(
                action_data=action_data,
                reasoning=reasoning,
                cycle_timers=cycle_timers,
                thinking_id=thinking_id,
                chat_stream=chat_stream,
                log_prefix=log_prefix,
                shutting_down=shutting_down,
                plugin_config=plugin_config,
                action_message=action_message,
            )

            logger.debug(f"创建Action实例成功: {action_name}")
            return instance

        except Exception as e:
            logger.error(f"创建Action实例失败 {action_name}: {e}")
            logger.error(traceback.format_exc())
            return None

    def get_using_actions(self) -> dict[str, ActionInfo]:
        """获取当前正在使用的动作集合"""
        return self._using_actions.copy()

    def remove_action_from_using(self, action_name: str) -> bool:
        """从当前使用的动作集中移除指定动作"""
        if action_name not in self._using_actions:
            logger.warning(f"移除失败: 动作 {action_name} 不在当前使用的动作集中")
            return False

        del self._using_actions[action_name]
        logger.debug(f"已从使用集中移除动作 {action_name}")
        return True

    async def restore_actions(self) -> None:
        """恢复到当前 stream_id 的默认动作集"""
        actions_to_restore = list(self._using_actions.keys())
        await self.load_actions(self.chat_id)
        logger.debug(f"恢复动作集: 从 {actions_to_restore} 恢复到 stream '{self.chat_id}' 的默认动作集 {list(self._using_actions.keys())}")

    async def execute_action(
        self,
        action_name: str,
        chat_id: str,
        target_message: DatabaseMessages | None = None,
        reasoning: str = "",
        action_data: dict | None = None,
        thinking_id: str | None = None,
        log_prefix: str = "",
        clear_unread_messages: bool = True,
    ) -> Any:
        """
        执行单个动作
        
        所有动作逻辑都在 BaseAction.execute() 中实现

        Args:
            action_name: 动作名称
            chat_id: 聊天ID
            target_message: 目标消息
            reasoning: 执行理由
            action_data: 动作数据
            thinking_id: 思考ID
            log_prefix: 日志前缀
            clear_unread_messages: 是否清除未读消息

        Returns:
            执行结果字典
        """
        chat_stream = None
        try:
            # 获取 chat_stream
            chat_manager = get_chat_manager()
            chat_stream = await chat_manager.get_stream(chat_id)

            if not chat_stream:
                logger.error(f"{log_prefix} 无法找到 chat_stream: {chat_id}")
                return {
                    "action_type": action_name,
                    "success": False,
                    "reply_text": "",
                    "error": "chat_stream not found",
                }

            # 设置正在处理的状态
            chat_stream.context.is_replying = True

            # no_action 特殊处理
            if action_name == "no_action":
                return {"action_type": "no_action", "success": True, "reply_text": ""}

            # 创建并执行动作
            action_handler = self.create_action(
                action_name=action_name,
                action_data=action_data or {},
                reasoning=reasoning,
                cycle_timers={},
                thinking_id=thinking_id or "",
                chat_stream=chat_stream,
                log_prefix=log_prefix or self.log_prefix,
                action_message=target_message,
            )

            if not action_handler:
                logger.error(f"{log_prefix} 创建动作处理器失败: {action_name}")
                return {
                    "action_type": action_name,
                    "success": False,
                    "reply_text": "",
                    "error": f"Failed to create action handler: {action_name}",
                }

            # 执行动作
            success, reply_text = await action_handler.handle_action()

            # 记录动作到消息并存储动作信息
            if success:
                asyncio.create_task(self._record_action_to_message(chat_stream, action_name, target_message, action_data))
                asyncio.create_task(self._reset_interruption_count(chat_stream.stream_id))
                # 统一存储动作信息
                asyncio.create_task(
                    self._store_action_info(
                        action_handler=action_handler,
                        action_name=action_name,
                        reply_text=reply_text,
                        target_message=target_message,
                    )
                )

            return {
                "action_type": action_name,
                "success": success,
                "reply_text": reply_text,
            }

        except Exception as e:
            logger.error(f"{log_prefix} 执行动作时出错: {e}")
            logger.error(traceback.format_exc())
            return {
                "action_type": action_name,
                "success": False,
                "reply_text": "",
                "error": str(e),
            }
        finally:
            if chat_stream:
                chat_stream.context.is_replying = False

    async def _record_action_to_message(self, chat_stream, action_name: str, target_message, action_data: dict | None):
        """记录执行的动作到目标消息"""
        try:
            from src.chat.message_manager.message_manager import message_manager

            target_message_id = None
            if target_message:
                target_message_id = target_message.message_id
            elif action_data and isinstance(action_data, dict):
                target_message_id = action_data.get("target_message_id")

            if not target_message_id:
                return

            await message_manager.add_action(
                stream_id=chat_stream.stream_id,
                message_id=target_message_id,
                action=action_name,
            )
            logger.debug(f"已记录动作 {action_name} 到消息 {target_message_id}")

        except Exception as e:
            logger.error(f"记录动作到消息失败: {e}")

    async def _reset_interruption_count(self, stream_id: str):
        """重置打断计数"""
        try:
            chat_manager = get_chat_manager()
            chat_stream = await chat_manager.get_stream(stream_id)
            if chat_stream and chat_stream.context.interruption_count > 0:
                old_count = chat_stream.context.interruption_count
                await chat_stream.context.reset_interruption_count()
                logger.debug(f"重置打断计数: {old_count} -> 0")
        except Exception as e:
            logger.warning(f"重置打断计数时出错: {e}")

    async def _store_action_info(
        self,
        action_handler: BaseAction,
        action_name: str,
        reply_text: str,
        target_message: DatabaseMessages | None,
    ):
        """统一存储动作信息到数据库"""
        try:
            from src.person_info.person_info import get_person_info_manager
            from src.plugin_system.apis import database_api

            # 构建 action_prompt_display
            action_prompt_display = ""
            if reply_text:
                person_info_manager = get_person_info_manager()
                if target_message:
                    platform = target_message.chat_info.platform
                    user_id = target_message.user_info.user_id
                    person_id = person_info_manager.get_person_id(platform, user_id)
                    person_name = await person_info_manager.get_value(person_id, "person_name")
                    action_prompt_display = f"你对{person_name}进行了回复：{reply_text}"
                else:
                    action_prompt_display = f"统一回应：{reply_text}"

            # 存储动作信息
            await database_api.store_action_info(
                chat_stream=action_handler.chat_stream,
                action_build_into_prompt=False,
                action_prompt_display=action_prompt_display,
                action_done=True,
                thinking_id=action_handler.thinking_id,
                action_data={"reply_text": reply_text} if reply_text else action_handler.action_data,
                action_name=action_name,
            )
            logger.debug(f"已存储动作信息: {action_name}")

        except Exception as e:
            logger.error(f"存储动作信息失败: {e}")
