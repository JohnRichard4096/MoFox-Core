import time
from typing import Optional, Dict, Any, Union

from src.common.logger import get_logger
from src.chat.message_receive.chat_stream import get_chat_manager
from src.plugin_system.apis import send_api
from maim_message.message_base import GroupInfo


logger = get_logger("hfc")


class CycleDetail:
    """
    循环信息记录类

    功能说明:
    - 记录单次思考循环的详细信息
    - 包含循环ID、思考ID、时间戳等基本信息
    - 存储循环的规划信息和动作信息
    - 提供序列化和转换功能
    """

    def __init__(self, cycle_id: Union[int, str]):
        """
        初始化循环详情记录

        Args:
            cycle_id: 循环ID，用于标识循环的顺序

        功能说明:
        - 设置循环基本标识信息
        - 初始化时间戳和计时器
        - 准备循环信息存储容器
        """
        self.cycle_id = cycle_id
        self.thinking_id = ""
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.timers: Dict[str, float] = {}

        self.loop_plan_info: Dict[str, Any] = {}
        self.loop_action_info: Dict[str, Any] = {}

    def to_dict(self) -> Dict[str, Any]:
        """
        将循环信息转换为字典格式

        Returns:
            dict: 包含所有循环信息的字典，已处理循环引用和序列化问题

        功能说明:
        - 递归转换复杂对象为可序列化格式
        - 防止循环引用导致的无限递归
        - 限制递归深度避免栈溢出
        - 只保留基本数据类型和可序列化的值
        """

        def convert_to_serializable(obj, depth=0, seen=None):
            if seen is None:
                seen = set()

            # 防止递归过深
            if depth > 5:  # 降低递归深度限制
                return str(obj)

            # 防止循环引用
            obj_id = id(obj)
            if obj_id in seen:
                return str(obj)
            seen.add(obj_id)

            try:
                if hasattr(obj, "to_dict"):
                    # 对于有to_dict方法的对象，直接调用其to_dict方法
                    return obj.to_dict()
                elif isinstance(obj, dict):
                    # 对于字典，只保留基本类型和可序列化的值
                    return {
                        k: convert_to_serializable(v, depth + 1, seen)
                        for k, v in obj.items()
                        if isinstance(k, (str, int, float, bool))
                    }
                elif isinstance(obj, (list, tuple)):
                    # 对于列表和元组，只保留可序列化的元素
                    return [
                        convert_to_serializable(item, depth + 1, seen)
                        for item in obj
                        if not isinstance(item, (dict, list, tuple))
                        or isinstance(item, (str, int, float, bool, type(None)))
                    ]
                elif isinstance(obj, (str, int, float, bool, type(None))):
                    return obj
                else:
                    return str(obj)
            finally:
                seen.remove(obj_id)

        return {
            "cycle_id": self.cycle_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "timers": self.timers,
            "thinking_id": self.thinking_id,
            "loop_plan_info": convert_to_serializable(self.loop_plan_info),
            "loop_action_info": convert_to_serializable(self.loop_action_info),
        }

    def set_loop_info(self, loop_info: Dict[str, Any]):
        """
        设置循环信息

        Args:
            loop_info: 包含循环规划和动作信息的字典

        功能说明:
        - 从传入的循环信息中提取规划和动作信息
        - 更新当前循环详情的相关字段
        """
        self.loop_plan_info = loop_info["loop_plan_info"]
        self.loop_action_info = loop_info["loop_action_info"]


async def send_typing():
    """
    发送打字状态指示

    功能说明:
    - 创建内心聊天流（用于状态显示）
    - 发送typing状态消息
    - 不存储到消息记录中
    - 用于S4U功能的视觉反馈
    """
    group_info = GroupInfo(platform="amaidesu_default", group_id="114514", group_name="内心")

    chat = await get_chat_manager().get_or_create_stream(
        platform="amaidesu_default",
        user_info=None,
        group_info=group_info,
    )

    await send_api.custom_to_stream(
        message_type="state", content="typing", stream_id=chat.stream_id, storage_message=False
    )


async def stop_typing():
    """
    停止打字状态指示

    功能说明:
    - 创建内心聊天流（用于状态显示）
    - 发送stop_typing状态消息
    - 不存储到消息记录中
    - 结束S4U功能的视觉反馈
    """
    group_info = GroupInfo(platform="amaidesu_default", group_id="114514", group_name="内心")

    chat = await get_chat_manager().get_or_create_stream(
        platform="amaidesu_default",
        user_info=None,
        group_info=group_info,
    )

    await send_api.custom_to_stream(
        message_type="state", content="stop_typing", stream_id=chat.stream_id, storage_message=False
    )
