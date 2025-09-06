import asyncio
import random
from datetime import datetime, timedelta, date, time
from enum import Enum, auto
from typing import Optional, TYPE_CHECKING

from src.common.logger import get_logger
from src.config.config import global_config
from src.manager.local_store_manager import local_storage
from src.plugin_system.apis import send_api, generator_api

if TYPE_CHECKING:
    from mmc.src.chat.chat_loop.sleep_manager.wakeup_manager import WakeUpManager

logger = get_logger("sleep_manager")


class SleepState(Enum):
    """睡眠状态枚举"""

    AWAKE = auto()  # 完全清醒
    INSOMNIA = auto()  # 失眠（在理论睡眠时间内保持清醒）
    PREPARING_SLEEP = auto()  # 准备入睡（缓冲期）
    SLEEPING = auto()  # 正在休眠
    WOKEN_UP = auto()  # 被吵醒


class SleepManager:
    def __init__(self, bridge):
        self.bridge = bridge
        self.last_sleep_log_time = 0
        self.sleep_log_interval = 35  # 日志记录间隔，单位秒

        # --- 统一睡眠状态管理 ---
        self._current_state: SleepState = SleepState.AWAKE
        self._sleep_buffer_end_time: Optional[datetime] = None
        self._total_delayed_minutes_today: int = 0
        self._last_sleep_check_date: Optional[date] = None
        self._last_fully_slept_log_time: float = 0
        self._re_sleep_attempt_time: Optional[datetime] = None  # 新增：重新入睡的尝试时间

        self._load_sleep_state()

    def get_current_sleep_state(self) -> SleepState:
        """获取当前的睡眠状态"""
        return self._current_state

    def is_sleeping(self) -> bool:
        """检查当前是否处于正式休眠状态"""
        return self._current_state == SleepState.SLEEPING

    async def update_sleep_state(self, wakeup_manager: Optional["WakeUpManager"] = None):
        """
        核心状态机：根据当前情况更新睡眠状态
        """
        # --- 基础检查 ---
        today_schedule = self.bridge.get_today_schedule()
        if not global_config.sleep_system.enable or not today_schedule:
            if self._current_state != SleepState.AWAKE:
                logger.debug("睡眠系统禁用或无日程，强制设为 AWAKE")
                self._current_state = SleepState.AWAKE
            return

        now = datetime.now()
        today = now.date()

        # --- 每日状态重置 ---
        if self._last_sleep_check_date != today:
            logger.info(f"新的一天 ({today})，重置睡眠状态为 AWAKE。")
            self._total_delayed_minutes_today = 0
            self._current_state = SleepState.AWAKE
            self._sleep_buffer_end_time = None
            self._last_sleep_check_date = today
            self._save_sleep_state()

        # --- 判断当前是否为理论上的睡眠时间 ---
        is_in_theoretical_sleep, activity = self._is_in_theoretical_sleep_time(now.time())

        # ===================================
        #  状态机核心逻辑
        # ===================================

        # 状态：清醒 (AWAKE)
        if self._current_state == SleepState.AWAKE:
            if is_in_theoretical_sleep:
                logger.info(f"进入理论休眠时间 '{activity}'，开始进行睡眠决策...")

                # --- 合并后的失眠与弹性睡眠决策逻辑 ---
                sleep_pressure = wakeup_manager.context.sleep_pressure if wakeup_manager else 999
                pressure_threshold = global_config.sleep_system.flexible_sleep_pressure_threshold

                # 决策1：因睡眠压力低而延迟入睡（原弹性睡眠）
                if (
                    sleep_pressure < pressure_threshold
                    and self._total_delayed_minutes_today < global_config.sleep_system.max_sleep_delay_minutes
                ):
                    delay_minutes = 15
                    self._total_delayed_minutes_today += delay_minutes
                    self._sleep_buffer_end_time = now + timedelta(minutes=delay_minutes)
                    self._current_state = SleepState.INSOMNIA
                    logger.info(
                        f"睡眠压力 ({sleep_pressure:.1f}) 低于阈值 ({pressure_threshold})，进入失眠状态，延迟入睡 {delay_minutes} 分钟。"
                    )

                    # 发送睡前通知
                    if global_config.sleep_system.enable_pre_sleep_notification:
                        asyncio.create_task(self._send_pre_sleep_notification())

                # 决策2：进入正常的入睡准备流程
                else:
                    buffer_seconds = random.randint(5 * 60, 10 * 60)
                    self._sleep_buffer_end_time = now + timedelta(seconds=buffer_seconds)
                    self._current_state = SleepState.PREPARING_SLEEP
                    logger.info(
                        f"睡眠压力正常或已达今日最大延迟，进入准备入睡状态，将在 {buffer_seconds / 60:.1f} 分钟内入睡。"
                    )

                    # 发送睡前通知
                    if global_config.sleep_system.enable_pre_sleep_notification:
                        asyncio.create_task(self._send_pre_sleep_notification())

                self._save_sleep_state()

        # 状态：失眠 (INSOMNIA)
        elif self._current_state == SleepState.INSOMNIA:
            if not is_in_theoretical_sleep:
                logger.info("已离开理论休眠时间，失眠结束，恢复清醒。")
                self._current_state = SleepState.AWAKE
                self._save_sleep_state()
            elif self._sleep_buffer_end_time and now >= self._sleep_buffer_end_time:
                logger.info("失眠状态下的延迟时间已过，重新评估是否入睡...")
                sleep_pressure = wakeup_manager.context.sleep_pressure if wakeup_manager else 999
                pressure_threshold = global_config.sleep_system.flexible_sleep_pressure_threshold

                if (
                    sleep_pressure >= pressure_threshold
                    or self._total_delayed_minutes_today >= global_config.sleep_system.max_sleep_delay_minutes
                ):
                    logger.info("睡眠压力足够或已达最大延迟，从失眠状态转换到准备入睡。")
                    buffer_seconds = random.randint(5 * 60, 10 * 60)
                    self._sleep_buffer_end_time = now + timedelta(seconds=buffer_seconds)
                    self._current_state = SleepState.PREPARING_SLEEP
                else:
                    logger.info(f"睡眠压力({sleep_pressure:.1f})仍然较低，再延迟15分钟。")
                    delay_minutes = 15
                    self._total_delayed_minutes_today += delay_minutes
                    self._sleep_buffer_end_time = now + timedelta(minutes=delay_minutes)

                self._save_sleep_state()

        # 状态：准备入睡 (PREPARING_SLEEP)
        elif self._current_state == SleepState.PREPARING_SLEEP:
            if not is_in_theoretical_sleep:
                logger.info("准备入睡期间离开理论休眠时间，取消入睡，恢复清醒。")
                self._current_state = SleepState.AWAKE
                self._sleep_buffer_end_time = None
                self._save_sleep_state()
            elif self._sleep_buffer_end_time and now >= self._sleep_buffer_end_time:
                logger.info("睡眠缓冲期结束，正式进入休眠状态。")
                self._current_state = SleepState.SLEEPING
                self._last_fully_slept_log_time = now.timestamp()
                self._save_sleep_state()

        # 状态：休眠中 (SLEEPING)
        elif self._current_state == SleepState.SLEEPING:
            if not is_in_theoretical_sleep:
                logger.info("理论休眠时间结束，自然醒来。")
                self._current_state = SleepState.AWAKE
                self._save_sleep_state()
            else:
                # 记录日志
                current_timestamp = now.timestamp()
                if current_timestamp - self.last_sleep_log_time > self.sleep_log_interval:
                    logger.info(f"当前处于休眠活动 '{activity}' 中。")
                    self.last_sleep_log_time = current_timestamp

        # 状态：被吵醒 (WOKEN_UP)
        elif self._current_state == SleepState.WOKEN_UP:
            if not is_in_theoretical_sleep:
                logger.info("理论休眠时间结束，被吵醒的状态自动结束。")
                self._current_state = SleepState.AWAKE
                self._re_sleep_attempt_time = None
                self._save_sleep_state()
            elif self._re_sleep_attempt_time and now >= self._re_sleep_attempt_time:
                logger.info("被吵醒后经过一段时间，尝试重新入睡...")

                sleep_pressure = wakeup_manager.context.sleep_pressure if wakeup_manager else 999
                pressure_threshold = global_config.sleep_system.flexible_sleep_pressure_threshold

                if sleep_pressure >= pressure_threshold:
                    logger.info("睡眠压力足够，从被吵醒状态转换到准备入睡。")
                    buffer_seconds = random.randint(3 * 60, 8 * 60)  # 重新入睡的缓冲期可以短一些
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
        """被唤醒后，将状态切换到 WOKEN_UP"""
        if self._current_state in [SleepState.PREPARING_SLEEP, SleepState.SLEEPING, SleepState.INSOMNIA]:
            logger.info("被唤醒，进入 WOKEN_UP 状态！")
            self._current_state = SleepState.WOKEN_UP
            self._sleep_buffer_end_time = None

            # 设置一个延迟，之后再尝试重新入睡
            re_sleep_delay_minutes = getattr(global_config.sleep_system, "re_sleep_delay_minutes", 10)
            self._re_sleep_attempt_time = datetime.now() + timedelta(minutes=re_sleep_delay_minutes)
            logger.info(f"将在 {re_sleep_delay_minutes} 分钟后尝试重新入睡。")

            self._save_sleep_state()

    def _is_in_theoretical_sleep_time(self, now_time: time) -> tuple[bool, Optional[str]]:
        """检查当前时间是否落在日程表的任何一个睡眠活动中"""
        sleep_keywords = ["休眠", "睡觉", "梦乡"]
        today_schedule = self.bridge.get_today_schedule()
        if today_schedule:
            for event in today_schedule:
                try:
                    activity = event.get("activity", "").strip()
                    time_range = event.get("time_range")

                    if not activity or not time_range:
                        continue

                    if any(keyword in activity for keyword in sleep_keywords):
                        start_str, end_str = time_range.split("-")
                        start_time = datetime.strptime(start_str.strip(), "%H:%M").time()
                        end_time = datetime.strptime(end_str.strip(), "%H:%M").time()

                        if start_time <= end_time:  # 同一天
                            if start_time <= now_time < end_time:
                                return True, activity
                        else:  # 跨天
                            if now_time >= start_time or now_time < end_time:
                                return True, activity
                except (ValueError, KeyError, AttributeError) as e:
                    logger.warning(f"解析日程事件时出错: {event}, 错误: {e}")
                    continue

        return False, None

    async def _send_pre_sleep_notification(self):
        """异步生成并发送睡前通知"""
        try:
            groups = global_config.sleep_system.pre_sleep_notification_groups
            prompt = global_config.sleep_system.pre_sleep_prompt

            if not groups:
                logger.info("未配置睡前通知的群组，跳过发送。")
                return

            if not prompt:
                logger.warning("睡前通知的prompt为空，跳过发送。")
                return

            # 为防止消息风暴，稍微延迟一下
            await asyncio.sleep(random.uniform(5, 15))

            for group_id_str in groups:
                try:
                    # 格式 "platform:group_id"
                    parts = group_id_str.split(":")
                    if len(parts) != 2:
                        logger.warning(f"无效的群组ID格式: {group_id_str}")
                        continue

                    platform, group_id = parts

                    # 使用与 ChatStream.get_stream_id 相同的逻辑生成 stream_id
                    import hashlib

                    key = "_".join([platform, group_id])
                    stream_id = hashlib.md5(key.encode()).hexdigest()

                    logger.info(f"正在为群组 {group_id_str} (Stream ID: {stream_id}) 生成睡前消息...")

                    # 调用 generator_api 生成回复
                    success, reply_set, _ = await generator_api.generate_reply(
                        chat_id=stream_id, extra_info=prompt, request_type="schedule.pre_sleep_notification"
                    )

                    if success and reply_set:
                        # 提取文本内容并发送
                        reply_text = "".join([content for msg_type, content in reply_set if msg_type == "text"])
                        if reply_text:
                            logger.info(f"向群组 {group_id_str} 发送睡前消息: {reply_text}")
                            await send_api.text_to_stream(text=reply_text, stream_id=stream_id)
                        else:
                            logger.warning(f"为群组 {group_id_str} 生成的回复内容为空。")
                    else:
                        logger.error(f"为群组 {group_id_str} 生成睡前消息失败。")

                    await asyncio.sleep(random.uniform(2, 5))  # 避免发送过快

                except Exception as e:
                    logger.error(f"向群组 {group_id_str} 发送睡前消息失败: {e}")

        except Exception as e:
            logger.error(f"发送睡前通知任务失败: {e}")

    def _save_sleep_state(self):
        """将当前睡眠状态保存到本地存储"""
        try:
            state = {
                "current_state": self._current_state.name,
                "sleep_buffer_end_time_ts": self._sleep_buffer_end_time.timestamp()
                if self._sleep_buffer_end_time
                else None,
                "total_delayed_minutes_today": self._total_delayed_minutes_today,
                "last_sleep_check_date_str": self._last_sleep_check_date.isoformat()
                if self._last_sleep_check_date
                else None,
                "re_sleep_attempt_time_ts": self._re_sleep_attempt_time.timestamp()
                if self._re_sleep_attempt_time
                else None,
            }
            local_storage["schedule_sleep_state"] = state
            logger.debug(f"已保存睡眠状态: {state}")
        except Exception as e:
            logger.error(f"保存睡眠状态失败: {e}")

    def _load_sleep_state(self):
        """从本地存储加载睡眠状态"""
        try:
            state = local_storage["schedule_sleep_state"]
            if state and isinstance(state, dict):
                state_name = state.get("current_state")
                if state_name and hasattr(SleepState, state_name):
                    self._current_state = SleepState[state_name]

                end_time_ts = state.get("sleep_buffer_end_time_ts")
                if end_time_ts:
                    self._sleep_buffer_end_time = datetime.fromtimestamp(end_time_ts)

                re_sleep_ts = state.get("re_sleep_attempt_time_ts")
                if re_sleep_ts:
                    self._re_sleep_attempt_time = datetime.fromtimestamp(re_sleep_ts)

                self._total_delayed_minutes_today = state.get("total_delayed_minutes_today", 0)

                date_str = state.get("last_sleep_check_date_str")
                if date_str:
                    self._last_sleep_check_date = datetime.fromisoformat(date_str).date()

                logger.info(f"成功从本地存储加载睡眠状态: {state}")
        except Exception as e:
            logger.warning(f"加载睡眠状态失败，将使用默认值: {e}")
