import asyncio
import random
from datetime import datetime, timedelta, date
from typing import Optional, TYPE_CHECKING, List, Dict, Any

from src.common.logger import get_logger
from src.config.config import global_config
from .sleep_state import SleepState, SleepStateSerializer
from .time_checker import TimeChecker
from .notification_sender import NotificationSender

if TYPE_CHECKING:
    from mmc.src.chat.chat_loop.sleep_manager.wakeup_manager import WakeUpManager

logger = get_logger("sleep_manager")


class SleepManager:
    def __init__(self):
        self.time_checker = TimeChecker(self)
        self.today_schedule: Optional[List[Dict[str, Any]]] = None
        self.last_sleep_log_time = 0
        self.sleep_log_interval = 35

        # --- 统一睡眠状态管理 ---
        self._current_state: SleepState = SleepState.AWAKE
        self._sleep_buffer_end_time: Optional[datetime] = None
        self._total_delayed_minutes_today: int = 0
        self._last_sleep_check_date: Optional[date] = None
        self._last_fully_slept_log_time: float = 0
        self._re_sleep_attempt_time: Optional[datetime] = None

        self._load_sleep_state()

    def get_current_sleep_state(self) -> SleepState:
        return self._current_state

    def is_sleeping(self) -> bool:
        return self._current_state == SleepState.SLEEPING

    async def update_sleep_state(self, wakeup_manager: Optional["WakeUpManager"] = None):
        if not global_config.sleep_system.enable:
            if self._current_state != SleepState.AWAKE:
                logger.debug("睡眠系统禁用，强制设为 AWAKE")
                self._current_state = SleepState.AWAKE
            return

        now = datetime.now()
        today = now.date()

        if self._last_sleep_check_date != today:
            logger.info(f"新的一天 ({today})，重置睡眠状态。")
            self._total_delayed_minutes_today = 0
            self._current_state = SleepState.AWAKE
            self._sleep_buffer_end_time = None
            self._last_sleep_check_date = today
            self._save_sleep_state()

        is_in_theoretical_sleep, activity = self.time_checker.is_in_theoretical_sleep_time(now.time())

        # 状态机处理
        if self._current_state == SleepState.AWAKE:
            if is_in_theoretical_sleep:
                self._handle_awake_to_sleep(now, activity, wakeup_manager)

        elif self._current_state == SleepState.PREPARING_SLEEP:
            self._handle_preparing_sleep(now, is_in_theoretical_sleep, wakeup_manager)

        elif self._current_state == SleepState.SLEEPING:
            self._handle_sleeping(now, is_in_theoretical_sleep, activity, wakeup_manager)

        elif self._current_state == SleepState.INSOMNIA:
            self._handle_insomnia(now, is_in_theoretical_sleep)

        elif self._current_state == SleepState.WOKEN_UP:
            self._handle_woken_up(now, is_in_theoretical_sleep, wakeup_manager)

    def _handle_awake_to_sleep(self, now: datetime, activity: Optional[str], wakeup_manager: Optional["WakeUpManager"]):
        if activity:
            logger.info(f"进入理论休眠时间 '{activity}'，开始进行睡眠决策...")
        else:
            logger.info("进入理论休眠时间，开始进行睡眠决策...")
        
        if wakeup_manager and global_config.sleep_system.enable_pre_sleep_notification:
            asyncio.create_task(NotificationSender.send_goodnight_notification(wakeup_manager.context))

        buffer_seconds = random.randint(1 * 60, 3 * 60)
        self._sleep_buffer_end_time = now + timedelta(seconds=buffer_seconds)
        self._current_state = SleepState.PREPARING_SLEEP
        logger.info(f"进入准备入睡状态，将在 {buffer_seconds / 60:.1f} 分钟内入睡。")
        self._save_sleep_state()

    def _handle_preparing_sleep(self, now: datetime, is_in_theoretical_sleep: bool, wakeup_manager: Optional["WakeUpManager"]):
        if not is_in_theoretical_sleep:
            logger.info("准备入睡期间离开理论休眠时间，取消入睡，恢复清醒。")
            self._current_state = SleepState.AWAKE
            self._sleep_buffer_end_time = None
            self._save_sleep_state()
        elif self._sleep_buffer_end_time and now >= self._sleep_buffer_end_time:
            logger.info("睡眠缓冲期结束，正式进入休眠状态。")
            self._current_state = SleepState.SLEEPING
            self._last_fully_slept_log_time = now.timestamp()
            
            delay_minutes_range = global_config.sleep_system.insomnia_trigger_delay_minutes
            delay_minutes = random.randint(delay_minutes_range[0], delay_minutes_range[1])
            self._sleep_buffer_end_time = now + timedelta(minutes=delay_minutes)
            logger.info(f"已设置睡后失眠检查，将在 {delay_minutes} 分钟后触发。")
            
            self._save_sleep_state()

    def _handle_sleeping(self, now: datetime, is_in_theoretical_sleep: bool, activity: Optional[str], wakeup_manager: Optional["WakeUpManager"]):
        if not is_in_theoretical_sleep:
            logger.info("理论休眠时间结束，自然醒来。")
            self._current_state = SleepState.AWAKE
            self._save_sleep_state()
        elif self._sleep_buffer_end_time and now >= self._sleep_buffer_end_time:
            if wakeup_manager:
                sleep_pressure = wakeup_manager.context.sleep_pressure
                pressure_threshold = global_config.sleep_system.flexible_sleep_pressure_threshold
                if sleep_pressure < pressure_threshold:
                    logger.info(f"睡眠压力 ({sleep_pressure:.1f}) 低于阈值 ({pressure_threshold})，触发睡后失眠。")
                    self._current_state = SleepState.INSOMNIA
                    
                    duration_minutes_range = global_config.sleep_system.insomnia_duration_minutes
                    duration_minutes = random.randint(duration_minutes_range[0], duration_minutes_range[1])
                    self._sleep_buffer_end_time = now + timedelta(minutes=duration_minutes)
                    
                    asyncio.create_task(NotificationSender.send_insomnia_notification(wakeup_manager.context))
                    logger.info(f"进入失眠状态，将持续 {duration_minutes} 分钟。")
                else:
                    logger.info(f"睡眠压力 ({sleep_pressure:.1f}) 正常，未触发睡后失眠。")
                    self._sleep_buffer_end_time = None
                self._save_sleep_state()
        else:
            current_timestamp = now.timestamp()
            if current_timestamp - self.last_sleep_log_time > self.sleep_log_interval and activity:
                logger.info(f"当前处于休眠活动 '{activity}' 中。")
                self.last_sleep_log_time = current_timestamp

    def _handle_insomnia(self, now: datetime, is_in_theoretical_sleep: bool):
        if not is_in_theoretical_sleep:
            logger.info("已离开理论休眠时间，失眠结束，恢复清醒。")
            self._current_state = SleepState.AWAKE
            self._sleep_buffer_end_time = None
            self._save_sleep_state()
        elif self._sleep_buffer_end_time and now >= self._sleep_buffer_end_time:
            logger.info("失眠状态持续时间已过，恢复睡眠。")
            self._current_state = SleepState.SLEEPING
            self._sleep_buffer_end_time = None
            self._save_sleep_state()

    def _handle_woken_up(self, now: datetime, is_in_theoretical_sleep: bool, wakeup_manager: Optional["WakeUpManager"]):
        if not is_in_theoretical_sleep:
            logger.info("理论休眠时间结束，被吵醒的状态自动结束。")
            self._current_state = SleepState.AWAKE
            self._re_sleep_attempt_time = None
            self._save_sleep_state()
        elif self._re_sleep_attempt_time and now >= self._re_sleep_attempt_time:
            logger.info("被吵醒后经过一段时间，尝试重新入睡...")
            if wakeup_manager:
                sleep_pressure = wakeup_manager.context.sleep_pressure
                pressure_threshold = global_config.sleep_system.flexible_sleep_pressure_threshold

                if sleep_pressure >= pressure_threshold:
                    logger.info("睡眠压力足够，从被吵醒状态转换到准备入睡。")
                    buffer_seconds = random.randint(3 * 60, 8 * 60)
                    self._sleep_buffer_end_time = now + timedelta(seconds=buffer_seconds)
                    self._current_state = SleepState.PREPARING_SLEEP
                    self._re_sleep_attempt_time = None
                else:
                    delay_minutes = 15
                    self._re_sleep_attempt_time = now + timedelta(minutes=delay_minutes)
                    logger.info(
                        f"睡眠压力({sleep_pressure:.1f})仍然较低，暂时保持清醒，在 {delay_minutes} 分钟后再次尝试。"
                    )
                self._save_sleep_state()

    def reset_sleep_state_after_wakeup(self):
        if self._current_state in [SleepState.PREPARING_SLEEP, SleepState.SLEEPING, SleepState.INSOMNIA]:
            logger.info("被唤醒，进入 WOKEN_UP 状态！")
            self._current_state = SleepState.WOKEN_UP
            self._sleep_buffer_end_time = None
            re_sleep_delay_minutes = getattr(global_config.sleep_system, "re_sleep_delay_minutes", 10)
            self._re_sleep_attempt_time = datetime.now() + timedelta(minutes=re_sleep_delay_minutes)
            logger.info(f"将在 {re_sleep_delay_minutes} 分钟后尝试重新入睡。")
            self._save_sleep_state()

    def get_today_schedule(self) -> Optional[List[Dict[str, Any]]]:
        return self.today_schedule

    def update_today_schedule(self, schedule: Optional[List[Dict[str, Any]]]):
        self.today_schedule = schedule

    def _save_sleep_state(self):
        state_data = {
            "_current_state": self._current_state,
            "_sleep_buffer_end_time": self._sleep_buffer_end_time,
            "_total_delayed_minutes_today": self._total_delayed_minutes_today,
            "_last_sleep_check_date": self._last_sleep_check_date,
            "_re_sleep_attempt_time": self._re_sleep_attempt_time,
        }
        SleepStateSerializer.save(state_data)

    def _load_sleep_state(self):
        state_data = SleepStateSerializer.load()
        self._current_state = state_data["_current_state"]
        self._sleep_buffer_end_time = state_data["_sleep_buffer_end_time"]
        self._total_delayed_minutes_today = state_data["_total_delayed_minutes_today"]
        self._last_sleep_check_date = state_data["_last_sleep_check_date"]
        self._re_sleep_attempt_time = state_data["_re_sleep_attempt_time"]
