"""
Frequency-Based Proactive Trigger
=================================

本模块实现了一个周期性任务，用于根据用户的聊天频率来智能地触发主动思考。

核心功能:
- 定期运行，检查所有已知的私聊用户。
- 调用 ChatFrequencyAnalyzer 判断当前是否处于用户的高峰聊天时段。
- 如果满足条件（高峰时段、角色清醒、聊天循环空闲），则触发一次主动思考。
- 包含冷却机制，以避免在同一个高峰时段内重复打扰用户。

可配置参数:
- TRIGGER_CHECK_INTERVAL_SECONDS: 触发器检查的周期（秒）。
- COOLDOWN_HOURS: 在同一个高峰时段内触发一次后的冷却时间（小时）。
"""
import asyncio
import time
from datetime import datetime
from typing import Dict, Optional

from src.common.logger import get_logger
from src.chat.chat_loop.proactive.events import ProactiveTriggerEvent
from src.chat.heart_flow.heartflow import heartflow
from src.chat.chat_loop.sleep_manager.sleep_manager import SleepManager
from .analyzer import chat_frequency_analyzer

logger = get_logger("FrequencyBasedTrigger")

# --- 可配置参数 ---
# 触发器检查周期（秒）
TRIGGER_CHECK_INTERVAL_SECONDS = 60 * 5  # 5分钟
# 冷却时间（小时），确保在一个高峰时段只触发一次
COOLDOWN_HOURS = 3


class FrequencyBasedTrigger:
    """
    一个周期性任务，根据聊天频率分析结果来触发主动思考。
    """

    def __init__(self, sleep_manager: SleepManager):
        self._sleep_manager = sleep_manager
        self._task: Optional[asyncio.Task] = None
        # 记录上次为用户触发的时间，用于冷却控制
        # 格式: { "chat_id": timestamp }
        self._last_triggered: Dict[str, float] = {}

    async def _run_trigger_cycle(self):
        """触发器的主要循环逻辑。"""
        while True:
            try:
                await asyncio.sleep(TRIGGER_CHECK_INTERVAL_SECONDS)
                logger.debug("开始执行频率触发器检查...")

                # 1. 检查角色是否清醒
                if self._sleep_manager.is_sleeping():
                    logger.debug("角色正在睡眠，跳过本次频率触发检查。")
                    continue

                # 2. 获取所有已知的聊天ID
                #    【注意】这里我们假设所有 subheartflow 的 ID 就是 chat_id
                all_chat_ids = list(heartflow.subheartflows.keys())
                if not all_chat_ids:
                    continue

                now = datetime.now()
                
                for chat_id in all_chat_ids:
                    # 3. 检查是否处于冷却时间内
                    last_triggered_time = self._last_triggered.get(chat_id, 0)
                    if time.time() - last_triggered_time < COOLDOWN_HOURS * 3600:
                        continue

                    # 4. 检查当前是否是该用户的高峰聊天时间
                    if chat_frequency_analyzer.is_in_peak_time(chat_id, now):
                        
                        sub_heartflow = await heartflow.get_or_create_subheartflow(chat_id)
                        if not sub_heartflow:
                            logger.warning(f"无法为 {chat_id} 获取或创建 sub_heartflow。")
                            continue

                        # 5. 检查用户当前是否已有活跃的思考或回复任务
                        cycle_detail = sub_heartflow.heart_fc_instance.context.current_cycle_detail
                        if cycle_detail and not cycle_detail.end_time:
                            logger.debug(f"用户 {chat_id} 的聊天循环正忙（仍在周期 {cycle_detail.cycle_id} 中），本次不触发。")
                            continue
                         
                        logger.info(f"检测到用户 {chat_id} 处于聊天高峰期，且聊天循环空闲，准备触发主动思考。")
                        
                        # 6. 直接调用 proactive_thinker
                        event = ProactiveTriggerEvent(
                            source="frequency_analyzer",
                            reason="User is in a high-frequency chat period."
                        )
                        await sub_heartflow.heart_fc_instance.proactive_thinker.think(event)
                        
                        # 7. 更新触发时间，进入冷却
                        self._last_triggered[chat_id] = time.time()

            except asyncio.CancelledError:
                logger.info("频率触发器任务被取消。")
                break
            except Exception as e:
                logger.error(f"频率触发器循环发生未知错误: {e}", exc_info=True)
                # 发生错误后，等待更长时间再重试，避免刷屏
                await asyncio.sleep(TRIGGER_CHECK_INTERVAL_SECONDS * 2)

    def start(self):
        """启动触发器任务。"""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run_trigger_cycle())
            logger.info("基于聊天频率的主动思考触发器已启动。")

    def stop(self):
        """停止触发器任务。"""
        if self._task and not self._task.done():
            self._task.cancel()
            logger.info("基于聊天频率的主动思考触发器已停止。")
