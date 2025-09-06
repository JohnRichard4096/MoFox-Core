# mmc/src/chat/chat_loop/sleep_manager/schedule_bridge.py

"""
此模块充当 ScheduleManager 和 SleepManager 之间的桥梁，
将睡眠逻辑与日程生成逻辑解耦。
"""

from typing import Optional, TYPE_CHECKING, List, Dict, Any

from .sleep_manager import SleepManager, SleepState

if TYPE_CHECKING:
    from src.chat.chat_loop.sleep_manager.wakeup_manager import WakeUpManager


class ScheduleSleepBridge:
    def __init__(self):
        # 桥接器现在持有 SleepManager 的唯一实例
        self.sleep_manager = SleepManager(self)
        self.today_schedule: Optional[List[Dict[str, Any]]] = None

    def get_today_schedule(self) -> Optional[List[Dict[str, Any]]]:
        """
        向 SleepManager 提供当日日程。
        """
        return self.today_schedule

    def update_today_schedule(self, schedule: Optional[List[Dict[str, Any]]]):
        """
        由 ScheduleManager 调用以更新当日日程。
        """
        self.today_schedule = schedule

    # --- 代理方法，供应用程序的其他部分调用 ---

    def get_current_sleep_state(self) -> SleepState:
        """从 SleepManager 获取当前的睡眠状态。"""
        return self.sleep_manager.get_current_sleep_state()

    def is_sleeping(self) -> bool:
        """检查当前是否处于正式休眠状态。"""
        return self.sleep_manager.is_sleeping()

    async def update_sleep_state(self, wakeup_manager: Optional["WakeUpManager"] = None):
        """更新睡眠状态机。"""
        await self.sleep_manager.update_sleep_state(wakeup_manager)

    def reset_sleep_state_after_wakeup(self):
        """被唤醒后，将状态切换到 WOKEN_UP。"""
        self.sleep_manager.reset_sleep_state_after_wakeup()


# 创建一个全局可访问的桥接器单例
schedule_sleep_bridge = ScheduleSleepBridge()