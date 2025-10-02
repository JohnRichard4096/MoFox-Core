"""
好友动态监控服务
"""

import asyncio
import traceback
from collections.abc import Callable

from src.common.logger import get_logger

from .qzone_service import QZoneService

logger = get_logger("MaiZone.MonitorService")


class MonitorService:
    """好友动态监控服务"""

    def __init__(self, get_config: Callable, qzone_service: QZoneService):
        self.get_config = get_config
        self.qzone_service = qzone_service
        self.is_running = False
        self.task = None

    async def start(self):
        """启动监控任务"""
        if self.is_running:
            return
        self.is_running = True
        self.task = asyncio.create_task(self._monitor_loop())
        logger.info("好友动态监控任务已启动")

    async def stop(self):
        """停止监控任务"""
        if not self.is_running:
            return
        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("好友动态监控任务已停止")

    async def _monitor_loop(self):
        """监控任务主循环"""
        # 插件启动后，延迟一段时间再开始第一次监控
        await asyncio.sleep(60)

        while self.is_running:
            try:
                if not self.get_config("monitor.enable_auto_monitor", False):
                    await asyncio.sleep(60)
                    continue

                interval_minutes = self.get_config("monitor.interval_minutes", 10)

                await self.qzone_service.monitor_feeds()

                logger.info(f"本轮监控完成，将在 {interval_minutes} 分钟后进行下一次检查。")
                await asyncio.sleep(interval_minutes * 60)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"监控任务循环出错: {e}\n{traceback.format_exc()}")
                await asyncio.sleep(300)
